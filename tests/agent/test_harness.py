"""Tests for agent.harness.Harness."""

import json
import os
import tempfile

from agent.harness import Harness


class TestPathWhitelist:
    def test_path_whitelist_pass(self):
        h = Harness(path_whitelist=["/data/cfd"])
        result = h.before_call("loadFile", {"file_path": "/data/cfd/test.cgns"})
        assert result is None

    def test_path_whitelist_block(self):
        h = Harness(path_whitelist=["/data/cfd"])
        result = h.before_call("loadFile", {"file_path": "/etc/passwd"})
        assert result is not None
        assert "error" in result
        assert "whitelist" in result["error"]

    def test_no_whitelist_allows_all(self):
        h = Harness(path_whitelist=None)
        result = h.before_call("loadFile", {"file_path": "/any/path/file.cgns"})
        assert result is None

    def test_empty_whitelist_allows_all(self):
        h = Harness(path_whitelist=[])
        result = h.before_call("loadFile", {"file_path": "/any/path/file.cgns"})
        assert result is None


class TestCodingConfirm:
    def test_coding_confirm_block(self):
        h = Harness()
        result = h.before_call("run_bash", {"command": "echo hello"}, user_confirmed_coding=False)
        assert result is not None
        assert "error" in result

    def test_coding_confirm_pass(self):
        h = Harness()
        result = h.before_call("run_bash", {"command": "echo hello"}, user_confirmed_coding=True)
        assert result is None

    def test_dangerous_command(self):
        h = Harness()
        result = h.before_call("run_bash", {"command": "sudo rm -rf /"}, user_confirmed_coding=True)
        assert result is not None
        assert "Dangerous" in result["error"]

    def test_runPythonString_also_checked(self):
        h = Harness()
        result = h.before_call("runPythonString", {"command": "print(1)"}, user_confirmed_coding=False)
        assert result is not None
        assert "error" in result


class TestFileSizeCheck:
    def test_file_size_check_blocks_large(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".cgns") as f:
            # Write > 1 MB
            f.write(b"x" * (2 * 1024 * 1024))
            f.flush()
            path = f.name
        try:
            h = Harness(max_file_size_mb=1)
            result = h.before_call("loadFile", {"file_path": path})
            assert result is not None
            assert "too large" in result["error"]
        finally:
            os.unlink(path)

    def test_file_size_check_allows_small(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".cgns") as f:
            f.write(b"x" * 100)
            f.flush()
            path = f.name
        try:
            h = Harness(max_file_size_mb=1)
            result = h.before_call("loadFile", {"file_path": path})
            assert result is None
        finally:
            os.unlink(path)


class TestAfterCall:
    def test_truncate_short(self):
        h = Harness(max_return_chars=5000)
        result = {"summary": "ok", "data": [1, 2, 3]}
        assert h.after_call("calculate", result) == result

    def test_truncate_long(self):
        h = Harness(max_return_chars=100)
        big_data = list(range(1000))
        result = {"summary": "ok", "data": big_data}
        out = h.after_call("calculate", result)
        assert out["data"] == "[truncated]"
        assert out["summary"] == "ok"

    def test_non_dict_passthrough(self):
        h = Harness()
        assert h.after_call("test", "raw string") == "raw string"
