"""Credential handling — redaction and safe management of connection strings."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger("mcpdb.security.credentials")

# Patterns to redact in log messages
_SENSITIVE_PATTERNS = [
    re.compile(r"(password|passwd|pwd)\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"(api[_-]?key|apikey)\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"(secret|token)\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"://[^@/]+:[^@/]+@", re.IGNORECASE),  # user:pass@host
]

# Replacement for redacted content
_REDACTED = "***REDACTED***"


def redact_connection_string(connection_string: str) -> str:
    """Redact password from a database connection string.

    Input:  postgresql://user:secret_pass@host:5432/db
    Output: postgresql://user:***@host:5432/db
    """
    try:
        parsed = urlparse(connection_string)
        if parsed.password:
            safe = parsed._replace(
                netloc=f"{parsed.username}:***@{parsed.hostname}"
                + (f":{parsed.port}" if parsed.port else "")
            )
            return urlunparse(safe)
    except Exception:
        pass

    # Fallback: regex-based redaction
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", connection_string)


def redact_log_message(message: str) -> str:
    """Redact sensitive patterns from a log message."""
    result = message
    for pattern in _SENSITIVE_PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result


def redact_dict(data: dict[str, Any], sensitive_keys: set[str] | None = None) -> dict[str, Any]:
    """Redact sensitive values from a dictionary (shallow copy).

    Default sensitive keys: password, secret, token, api_key, apikey, credentials.
    """
    if sensitive_keys is None:
        sensitive_keys = {
            "password", "passwd", "pwd", "secret", "token",
            "api_key", "apikey", "credentials", "auth",
        }

    result = {}
    for key, value in data.items():
        if key.lower() in sensitive_keys:
            result[key] = _REDACTED
        elif isinstance(value, dict):
            result[key] = redact_dict(value, sensitive_keys)
        elif isinstance(value, str) and any(
            s in key.lower() for s in ("connection", "url", "uri", "dsn")
        ):
            result[key] = redact_connection_string(value)
        else:
            result[key] = value
    return result


def validate_no_disk_credentials(config: dict[str, Any]) -> list[str]:
    """Check that no credentials are stored directly in config files.

    Returns list of warnings about potential credential storage issues.
    """
    warnings = []

    def _check(d: dict[str, Any], path: str = "") -> None:
        for key, value in d.items():
            current_path = f"{path}.{key}" if path else key
            if isinstance(value, dict):
                _check(value, current_path)
            elif isinstance(value, str):
                if key.lower() in ("password", "secret", "token", "api_key", "apikey"):
                    if not value.startswith("${"):
                        warnings.append(
                            f"Credential at '{current_path}' is not using "
                            f"environment variable substitution"
                        )

    _check(config)
    return warnings
