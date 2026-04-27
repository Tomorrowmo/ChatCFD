"""MCP tool: runBash — Execute shell commands in a subprocess."""

import subprocess


def _run_command(command: str, timeout: int = 60, max_chars: int = 5000,
                 cwd: str = None) -> dict:
    """Execute a shell command and return stdout/stderr/exit_code."""
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
        )
        return {
            "stdout": proc.stdout[-max_chars:] if len(proc.stdout) > max_chars else proc.stdout,
            "stderr": proc.stderr[-max_chars:] if len(proc.stderr) > max_chars else proc.stderr,
            "exit_code": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "", "exit_code": -1,
                "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": -1,
                "error": str(e)}


def register(mcp, engine):
    @mcp.tool()
    def runBash(command: str, session_id: str = "default",
                timeout: int = 60) -> dict:
        """Execute a shell command. Requires user confirmation.
        Use for: ffmpeg, file conversion, system commands.
        Do NOT use for tasks achievable with existing tools (loadFile/calculate/exportData)."""
        state = engine.session_mgr.get(session_id)
        cwd = state.output_dir if state else None
        return _run_command(command, timeout=min(timeout, 120), cwd=cwd)
