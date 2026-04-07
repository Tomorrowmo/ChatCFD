"""Harness — hard safety constraints enforced in code."""

import json
import os


class Harness:
    def __init__(self, path_whitelist=None, max_file_size_mb=0, max_return_chars=5000):
        # max_file_size_mb=0 means no limit (local mode default)
        self.path_whitelist = [
            os.path.normpath(p).replace("\\", "/")
            for p in (path_whitelist or [])
        ]
        self.max_file_size_mb = max_file_size_mb
        self.max_return_chars = max_return_chars
        self.dangerous_commands = [
            "rm -rf /", "sudo", "shutdown", "reboot",
            "mkfs", "dd if=", ":(){:|:&};:",
        ]

    def before_call(self, tool_name, args, user_confirmed_coding=False):
        """Pre-call check. Returns error dict if blocked, else None."""
        file_path = args.get("file_path", "")

        # Path whitelist check
        if file_path and tool_name in ("loadFile", "exportData"):
            if not self._check_path(file_path):
                return {"error": f"Path not in whitelist: {file_path}"}

        # File size check (skip if limit is 0 = unlimited)
        if self.max_file_size_mb > 0 and tool_name == "loadFile" and file_path and os.path.exists(file_path):
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if size_mb > self.max_file_size_mb:
                return {"error": f"File too large: {size_mb:.0f}MB (limit: {self.max_file_size_mb}MB)"}

        # Coding confirmation check
        if tool_name in ("run_bash", "runPythonString"):
            if not user_confirmed_coding:
                return {"error": "需要用户确认后才能执行自定义代码。请先询问用户。"}
            cmd = args.get("command", "")
            for d in self.dangerous_commands:
                if d in cmd:
                    return {"error": f"Dangerous command blocked: {d}"}

        return None

    def after_call(self, tool_name, result):
        """Post-call processing: truncate oversized results."""
        if not isinstance(result, dict):
            return result
        serialized = json.dumps(result, ensure_ascii=False, default=str)
        if len(serialized) > self.max_return_chars:
            truncated = {k: v for k, v in result.items() if k != "data"}
            truncated["data"] = "[truncated]"
            return truncated
        return result

    def _check_path(self, file_path):
        if not self.path_whitelist:
            return True
        normalized = os.path.normpath(file_path).replace("\\", "/")
        return any(normalized.startswith(wp) for wp in self.path_whitelist)
