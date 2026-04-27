"""Tests for runBash MCP tool execution logic."""

import os
import importlib.util

_MOD_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../post_service/mcp_tools/run_bash.py"))
_spec = importlib.util.spec_from_file_location("run_bash", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_run_command = _mod._run_command


class TestRunCommand:
    def test_echo(self):
        result = _run_command("echo hello", timeout=10)
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]

    def test_stderr(self):
        result = _run_command("echo err >&2", timeout=10)
        assert "err" in result["stderr"]

    def test_exit_code(self):
        result = _run_command("exit 42", timeout=10)
        assert result["exit_code"] == 42

    def test_timeout(self):
        result = _run_command("python -c \"import time; time.sleep(60)\"", timeout=2)
        assert "timed out" in result.get("error", "").lower()

    def test_output_truncation(self):
        result = _run_command("python -c \"print('x'*20000)\"", timeout=10, max_chars=1000)
        assert len(result["stdout"]) <= 1000
