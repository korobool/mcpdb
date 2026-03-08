"""Python sandbox executor — runs code in an isolated subprocess."""

from __future__ import annotations

import base64
import io
import json
import logging
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from mcpdb.sandbox.security import ImportViolation, get_security, validate_imports

logger = logging.getLogger("mcpdb.sandbox")


@dataclass
class SandboxResult:
    """Result of sandbox execution."""
    stdout: str = ""
    stderr: str = ""
    success: bool = True
    error: str | None = None
    dataframe: pd.DataFrame | None = None
    charts: list[str] = field(default_factory=list)  # base64 PNG strings
    return_value: str | None = None


# The wrapper script template executed in the subprocess
_WRAPPER_SCRIPT = textwrap.dedent('''\
    import sys
    import json
    import io
    import base64

    # Apply resource limits
    {resource_limit_code}

    # Pre-inject libraries
    import pandas as pd
    import numpy as np
    try:
        import polars as pl
    except ImportError:
        pl = None

    _mcpdb_charts = []
    _mcpdb_df_result = None

    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt
        import seaborn as sns

        # Monkey-patch plt.show to capture figures
        _original_show = plt.show
        def _capture_show(*args, **kwargs):
            for fig_num in plt.get_fignums():
                fig = plt.figure(fig_num)
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
                buf.seek(0)
                _mcpdb_charts.append(base64.b64encode(buf.read()).decode("ascii"))
                buf.close()
            plt.close("all")
        plt.show = _capture_show

        # Monkey-patch plt.savefig to also capture (LLM may use savefig instead of show)
        _original_savefig = plt.savefig
        def _capture_savefig(*args, **kwargs):
            # Capture to our buffer first
            fig = plt.gcf()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
            buf.seek(0)
            _mcpdb_charts.append(base64.b64encode(buf.read()).decode("ascii"))
            buf.close()
            # Still save to the requested path (code may reference it)
            try:
                _original_savefig(*args, **kwargs)
            except Exception:
                pass
        plt.savefig = _capture_savefig
    except ImportError:
        plt = None
        sns = None

    # Load context DataFrame if provided
    df = None
    context_path = {context_path!r}
    if context_path:
        try:
            df = pd.read_json(context_path, orient="split")
        except Exception:
            pass

    # Execute user code
    _user_ns = {{
        "pd": pd, "np": np, "df": df,
        "plt": plt, "sns": sns, "pl": pl,
    }}
    try:
        exec({user_code!r}, _user_ns)
    except Exception as e:
        print(f"ERROR: {{type(e).__name__}}: {{e}}", file=sys.stderr)
        sys.exit(1)

    # Capture any plt figures not yet shown
    if plt is not None and plt.get_fignums():
        _capture_show()

    # Check if user code produced a new df (supports pandas and polars)
    if "result_df" in _user_ns:
        rdf = _user_ns["result_df"]
        if isinstance(rdf, pd.DataFrame):
            _mcpdb_df_result = rdf
        elif pl is not None and isinstance(rdf, pl.DataFrame):
            _mcpdb_df_result = rdf.to_pandas()
    elif "df" in _user_ns and _user_ns["df"] is not df:
        udf = _user_ns.get("df")
        if isinstance(udf, pd.DataFrame):
            _mcpdb_df_result = udf
        elif pl is not None and isinstance(udf, pl.DataFrame):
            _mcpdb_df_result = udf.to_pandas()

    # Write results to stdout as JSON envelope
    output = {{"_mcpdb_meta": True}}

    if _mcpdb_charts:
        output["charts"] = _mcpdb_charts

    if _mcpdb_df_result is not None:
        try:
            output["dataframe"] = _mcpdb_df_result.head(100).to_json(orient="split")
        except Exception:
            pass

    # Capture the last expression value if it looks useful
    print(json.dumps(output))
''')


def execute_python(
    code: str,
    context_df: pd.DataFrame | None = None,
    timeout: int = 30,
    memory_mb: int = 2048,
    cpu_seconds: int = 30,
) -> SandboxResult:
    """Execute Python code in an isolated subprocess.

    Args:
        code: Python code to execute.
        context_df: DataFrame to inject as `df` variable.
        timeout: Wall-clock timeout in seconds.
        memory_mb: Memory limit in MB.
        cpu_seconds: CPU time limit in seconds.

    Returns:
        SandboxResult with stdout, stderr, captured DataFrames and charts.
    """
    # Validate imports before execution
    security = get_security()
    violations = security.validate_imports(code)
    if violations:
        return SandboxResult(
            success=False,
            error=f"Import violations: {'; '.join(violations)}",
        )

    # Serialize context DataFrame to temp file
    context_path = None
    tmp_files = []

    try:
        if context_df is not None:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as ctx_file:
                context_df.to_json(ctx_file, orient="split")
                context_path = ctx_file.name
                tmp_files.append(ctx_file.name)

        # Build resource limit code
        resource_limit_code = _build_resource_limit_code(memory_mb, cpu_seconds)

        # Build the wrapper script
        script = _WRAPPER_SCRIPT.format(
            resource_limit_code=resource_limit_code,
            context_path=context_path or "",
            user_code=code,
        )

        # Write script to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as script_file:
            script_file.write(script)
            script_path = script_file.name
            tmp_files.append(script_path)

        # Execute in subprocess with controlled environment
        import os
        env = os.environ.copy()
        env["OPENBLAS_NUM_THREADS"] = "1"
        env["MKL_NUM_THREADS"] = "1"
        env["NUMEXPR_NUM_THREADS"] = "1"

        proc = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tempfile.gettempdir(),
            env=env,
        )

        return _parse_result(proc)

    except subprocess.TimeoutExpired:
        return SandboxResult(
            success=False,
            error=f"Execution timed out after {timeout} seconds",
        )
    except Exception as e:
        return SandboxResult(
            success=False,
            error=f"Sandbox error: {e}",
        )
    finally:
        # Clean up temp files
        for path in tmp_files:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass


def _build_resource_limit_code(memory_mb: int, cpu_seconds: int) -> str:
    """Generate code to apply resource limits inside the subprocess."""
    import platform
    if platform.system() != "Linux":
        return "pass  # Resource limits only on Linux"

    return textwrap.dedent(f"""\
        import resource
        try:
            resource.setrlimit(resource.RLIMIT_AS, ({memory_mb * 1024 * 1024}, {memory_mb * 1024 * 1024}))
            resource.setrlimit(resource.RLIMIT_CPU, ({cpu_seconds}, {cpu_seconds}))
        except Exception:
            pass  # Non-fatal if limits can't be set""")


def _parse_result(proc: subprocess.CompletedProcess) -> SandboxResult:
    """Parse subprocess output into SandboxResult."""
    result = SandboxResult()

    if proc.returncode != 0:
        result.success = False
        result.stderr = proc.stderr.strip()
        result.error = result.stderr or f"Process exited with code {proc.returncode}"
        # Still capture stdout even on failure
        result.stdout = proc.stdout.strip()
        return result

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    result.stderr = stderr

    # Try to parse the JSON envelope from the last line of stdout
    lines = stdout.split("\n")

    # Separate user stdout from our JSON metadata
    user_lines = []
    meta = None

    for line in lines:
        if meta is None:
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict) and parsed.get("_mcpdb_meta"):
                    meta = parsed
                    continue
            except (json.JSONDecodeError, ValueError):
                pass
        user_lines.append(line)

    # If meta not found yet, try the last line
    if meta is None and lines:
        try:
            parsed = json.loads(lines[-1])
            if isinstance(parsed, dict) and parsed.get("_mcpdb_meta"):
                meta = parsed
                user_lines = lines[:-1]
        except (json.JSONDecodeError, ValueError):
            pass

    result.stdout = "\n".join(user_lines).strip()

    if meta:
        # Extract charts
        result.charts = meta.get("charts", [])

        # Extract DataFrame
        df_json = meta.get("dataframe")
        if df_json:
            try:
                result.dataframe = pd.read_json(io.StringIO(df_json), orient="split")
            except Exception:
                pass

    return result
