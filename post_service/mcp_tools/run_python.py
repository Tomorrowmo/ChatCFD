"""MCP tool: runPython — Execute Python code in an isolated subprocess."""

import os
import re
import subprocess
import sys
import tempfile

# Detect available libraries once at import time.
# Add new libraries here when installed — PostService restart picks them up.
_CHECK_LIBS = [
    "numpy", "matplotlib", "PIL", "vtk", "pandas", "scipy",
    "imageio", "h5py", "pyvista", "trimesh",
]
_AVAILABLE = []
_UNAVAILABLE = []
for _lib in _CHECK_LIBS:
    try:
        __import__(_lib)
        _AVAILABLE.append(_lib)
    except ImportError:
        _UNAVAILABLE.append(_lib)
_LIB_DESC = f"Available: {', '.join(_AVAILABLE)}." if _AVAILABLE else ""
if _UNAVAILABLE:
    _LIB_DESC += f" NOT available: {', '.join(_UNAVAILABLE)}."


def _run_python(code: str, timeout: int = 60, max_chars: int = 5000,
                cwd: str = None) -> dict:
    """Write code to a temp file, execute in subprocess, collect output."""
    fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="chatcfd_code_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            proc = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True, text=True,
                timeout=timeout, cwd=cwd,
            )
            stdout = proc.stdout[-max_chars:] if len(proc.stdout) > max_chars else proc.stdout
            stderr = proc.stderr[-max_chars:] if len(proc.stderr) > max_chars else proc.stderr

            output_files = re.findall(r"CHATCFD_OUTPUT_FILE:(.+)", stdout)
            output_files = [p.strip() for p in output_files]
            stdout_clean = re.sub(r"CHATCFD_OUTPUT_FILE:.+\n?", "", stdout).strip()

            return {
                "stdout": stdout_clean,
                "stderr": stderr,
                "exit_code": proc.returncode,
                "output_files": output_files,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "", "exit_code": -1,
                    "output_files": [],
                    "error": f"Script timed out after {timeout}s"}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": -1,
                    "output_files": [], "error": str(e)}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def register(mcp, engine):
    @mcp.tool()
    def runPython(code: str, session_id: str = "default",
                  timeout: int = 60) -> dict:
        f"""Execute Python code in an isolated subprocess. Requires user confirmation.
        {_LIB_DESC} Use PIL for image/GIF operations.
        Output files: print 'CHATCFD_OUTPUT_FILE:/path/to/file' to report.
        Do NOT use for tasks achievable with existing tools."""
        state = engine.session_mgr.get(session_id)
        cwd = state.output_dir if state else None
        return _run_python(code, timeout=min(timeout, 120), max_chars=5000, cwd=cwd)
