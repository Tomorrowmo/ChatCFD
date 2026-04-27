"""Tests for runPython MCP tool execution logic."""

import os
import importlib.util

_MOD_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../post_service/mcp_tools/run_python.py"))
_spec = importlib.util.spec_from_file_location("run_python", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_run_python = _mod._run_python


class TestRunPython:
    def test_simple_print(self):
        result = _run_python("print('hello world')", timeout=10)
        assert result["exit_code"] == 0
        assert "hello world" in result["stdout"]

    def test_syntax_error(self):
        result = _run_python("def (broken", timeout=10)
        assert result["exit_code"] != 0
        assert "SyntaxError" in result["stderr"] or "invalid" in result["stderr"].lower()

    def test_numpy_available(self):
        result = _run_python("import numpy as np; print(np.array([1,2,3]).sum())", timeout=10)
        assert result["exit_code"] == 0
        assert "6" in result["stdout"]

    def test_output_file_detection(self, tmp_path):
        out = str(tmp_path / "test.txt").replace("\\\\", "/")
        code = f"path = r'{out}'\nwith open(path, 'w') as f:\n    f.write('test')\nprint(f'CHATCFD_OUTPUT_FILE:{{path}}')"
        result = _run_python(code, timeout=10)
        assert result["exit_code"] == 0
        assert len(result["output_files"]) == 1

    def test_timeout(self):
        result = _run_python("import time; time.sleep(60)", timeout=2)
        assert "timed out" in result.get("error", "").lower()

    def test_output_truncation(self):
        result = _run_python("print('x' * 20000)", timeout=10, max_chars=1000)
        assert len(result["stdout"]) <= 1000
