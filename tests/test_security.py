"""Tests for v3.5.x — Security Hardening."""

from __future__ import annotations

import pytest

from mcpdb.security.sql_safety import (
    SQLSafetyError,
    check_injection,
    check_read_only,
    sanitize_identifier,
    validate_sql,
)
from mcpdb.security.credentials import (
    redact_connection_string,
    redact_dict,
    redact_log_message,
    validate_no_disk_credentials,
)
from mcpdb.security.rate_limiter import (
    CircuitBreaker,
    CircuitBreakerOpen,
    ConcurrencyLimiter,
    RateLimiter,
    RateLimitExceeded,
)


# ---------------------------------------------------------------------------
# SQL safety
# ---------------------------------------------------------------------------

class TestReadOnly:
    def test_select_allowed(self):
        assert check_read_only("SELECT * FROM users") == []

    def test_select_with_joins(self):
        sql = "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
        assert check_read_only(sql) == []

    def test_insert_blocked(self):
        violations = check_read_only("INSERT INTO users (name) VALUES ('test')")
        assert len(violations) == 1
        assert "INSERT" in violations[0]

    def test_update_blocked(self):
        violations = check_read_only("UPDATE users SET name='test' WHERE id=1")
        assert len(violations) == 1

    def test_delete_blocked(self):
        violations = check_read_only("DELETE FROM users WHERE id=1")
        assert len(violations) == 1

    def test_drop_blocked(self):
        violations = check_read_only("DROP TABLE users")
        assert len(violations) == 1

    def test_create_blocked(self):
        violations = check_read_only("CREATE TABLE test (id INT)")
        assert len(violations) == 1

    def test_alter_blocked(self):
        violations = check_read_only("ALTER TABLE users ADD COLUMN email TEXT")
        assert len(violations) == 1

    def test_truncate_blocked(self):
        violations = check_read_only("TRUNCATE TABLE users")
        assert len(violations) >= 1

    def test_explain_allowed(self):
        assert check_read_only("EXPLAIN SELECT * FROM users") == []


class TestInjection:
    def test_clean_sql(self):
        assert check_injection("SELECT * FROM users WHERE id = 1") == []

    def test_semicolon_drop(self):
        warnings = check_injection("SELECT 1; DROP TABLE users")
        assert len(warnings) >= 1

    def test_into_outfile(self):
        warnings = check_injection("SELECT * INTO OUTFILE '/tmp/data'")
        assert len(warnings) >= 1

    def test_load_data(self):
        warnings = check_injection("LOAD DATA INFILE '/etc/passwd'")
        assert len(warnings) >= 1

    def test_load_file(self):
        warnings = check_injection("SELECT LOAD_FILE('/etc/passwd')")
        assert len(warnings) >= 1


class TestValidateSQL:
    def test_valid_select(self):
        validate_sql("SELECT * FROM users")  # should not raise

    def test_write_rejected(self):
        with pytest.raises(SQLSafetyError) as exc_info:
            validate_sql("DROP TABLE users")
        assert len(exc_info.value.violations) >= 1

    def test_write_allowed_when_not_readonly(self):
        validate_sql("INSERT INTO log (msg) VALUES ('test')", read_only=False)


class TestSanitizeIdentifier:
    def test_basic(self):
        assert sanitize_identifier("users") == "users"

    def test_with_schema(self):
        assert sanitize_identifier("public.users") == "public.users"

    def test_strips_special(self):
        assert sanitize_identifier("user; DROP TABLE --") == "userDROPTABLE"

    def test_reserved_word(self):
        result = sanitize_identifier("select")
        assert result == '"select"'

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            sanitize_identifier("")

    def test_all_special_raises(self):
        with pytest.raises(ValueError):
            sanitize_identifier("!@#$%")


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

class TestRedactConnectionString:
    def test_postgresql(self):
        result = redact_connection_string("postgresql://user:secret@host:5432/db")
        assert "secret" not in result
        assert "***" in result
        assert "user" in result
        assert "host" in result

    def test_mysql(self):
        result = redact_connection_string("mysql://admin:pass123@db.example.com/mydb")
        assert "pass123" not in result
        assert "***" in result

    def test_no_password(self):
        result = redact_connection_string("sqlite:///test.db")
        assert "test.db" in result

    def test_invalid_url(self):
        result = redact_connection_string("not a url")
        assert result == "not a url"


class TestRedactLogMessage:
    def test_password(self):
        msg = "Connecting with password=secret123"
        result = redact_log_message(msg)
        assert "secret123" not in result
        assert "REDACTED" in result

    def test_api_key(self):
        msg = "Using api_key=sk-abc123"
        result = redact_log_message(msg)
        assert "sk-abc123" not in result

    def test_connection_string(self):
        msg = "Connected to postgresql://user:pass@host/db"
        result = redact_log_message(msg)
        assert "pass" not in result

    def test_clean_message(self):
        msg = "Query completed in 42ms"
        assert redact_log_message(msg) == msg


class TestRedactDict:
    def test_password_key(self):
        result = redact_dict({"user": "admin", "password": "secret"})
        assert result["user"] == "admin"
        assert "secret" not in result["password"]

    def test_nested(self):
        result = redact_dict({"db": {"host": "localhost", "password": "pass"}})
        assert "pass" not in result["db"]["password"]

    def test_connection_url_key(self):
        result = redact_dict({"connection_url": "postgresql://user:pass@host/db"})
        assert "pass" not in result["connection_url"]

    def test_custom_keys(self):
        result = redact_dict({"foo": "bar"}, sensitive_keys={"foo"})
        assert "bar" not in result["foo"]


class TestNoDiskCredentials:
    def test_env_var_ok(self):
        config = {"llm": {"reasoning": {"api_key": "${MY_KEY}"}}}
        warnings = validate_no_disk_credentials(config)
        assert len(warnings) == 0

    def test_hardcoded_warning(self):
        config = {"llm": {"reasoning": {"api_key": "sk-actual-key"}}}
        warnings = validate_no_disk_credentials(config)
        assert len(warnings) == 1
        assert "api_key" in warnings[0]

    def test_no_sensitive_keys(self):
        config = {"llm": {"model": "test"}}
        assert validate_no_disk_credentials(config) == []


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_basic_acquire(self):
        rl = RateLimiter(max_per_minute=10)
        rl.acquire()  # should not raise
        assert rl.current_count() == 1

    def test_exceeds_limit(self):
        rl = RateLimiter(max_per_minute=3)
        rl.acquire()
        rl.acquire()
        rl.acquire()
        with pytest.raises(RateLimitExceeded):
            rl.acquire()

    def test_reset(self):
        rl = RateLimiter(max_per_minute=2)
        rl.acquire()
        rl.acquire()
        rl.reset()
        rl.acquire()  # should work after reset
        assert rl.current_count() == 1


class TestConcurrencyLimiter:
    def test_acquire_release(self):
        cl = ConcurrencyLimiter(max_concurrent=2)
        cl.acquire()
        assert cl.active_count == 1
        cl.release()
        assert cl.active_count == 0

    def test_exceeds_limit(self):
        cl = ConcurrencyLimiter(max_concurrent=1)
        cl.acquire()
        with pytest.raises(RateLimitExceeded):
            cl.acquire()
        cl.release()

    def test_release_after_exceed(self):
        cl = ConcurrencyLimiter(max_concurrent=1)
        cl.acquire()
        cl.release()
        cl.acquire()  # should work now


class TestCircuitBreaker:
    def test_initial_state(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == "closed"

    def test_stays_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_success()
        assert cb.state == "closed"

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"

    def test_open_blocks_requests(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        with pytest.raises(CircuitBreakerOpen):
            cb.check()

    def test_success_resets_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()  # only 1 now
        assert cb.state == "closed"

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        cb.reset()
        assert cb.state == "closed"

    def test_get_stats(self):
        cb = CircuitBreaker(failure_threshold=5, name="test")
        stats = cb.get_stats()
        assert stats["name"] == "test"
        assert stats["state"] == "closed"
        assert stats["threshold"] == 5

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"

        import time
        time.sleep(0.02)
        assert cb.state == "half_open"
