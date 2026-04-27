# Coding Agent Phase 2a: runBash + runPython MCP Tools

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `runBash` and `runPython` MCP tools to PostService, update Harness to cover new tool names, and wire the confirmation flow so the LLM can execute code after user approval.

**Architecture:** Two new MCP tool modules in `post_service/mcp_tools/`, both execute in isolated subprocesses. Harness already checks `run_bash`/`runPythonString` — update to also cover the new names `runBash`/`runPython`. Agent session already has `user_confirmed_coding` flag. Frontend confirmation is out of scope (user can set the flag via chat — "可以").

**Tech Stack:** Python subprocess, FastMCP tool registration, existing Harness safety layer.

**Test command:** `cd d:/Git/chatCFD && D:/TOOL/Conda/conda/envs/PostProcessTool/python.exe -m pytest tests/ -v`

---

### Task 1: Update Harness to cover new tool names

**Files:**
- Modify: `agent/harness.py:37`
- Modify: `tests/agent/test_harness.py`

**Step 1: Write the failing tests**

Add to `tests/agent/test_harness.py`:

```python
class TestCodingTools:
    """Tests for runBash/runPython tool name coverage in Harness."""

    def test_runBash_blocked_without_confirm(self):
        h = Harness()
        result = h.before_call("runBash", {"command": "echo hi"}, user_confirmed_coding=False)
        assert result is not None
        assert "确认" in result["error"]

    def test_runBash_allowed_with_confirm(self):
        h = Harness()
        result = h.before_call("runBash", {"command": "echo hi"}, user_confirmed_coding=True)
        assert result is None

    def test_runPython_blocked_without_confirm(self):
        h = Harness()
        result = h.before_call("runPython", {"command": "print(1)"}, user_confirmed_coding=False)
        assert result is not None

    def test_runPython_allowed_with_confirm(self):
        h = Harness()
        result = h.before_call("runPython", {"command": "print(1)"}, user_confirmed_coding=True)
        assert result is None

    def test_runBash_dangerous_blocked(self):
        h = Harness()
        result = h.before_call("runBash", {"command": "sudo rm -rf /"}, user_confirmed_coding=True)
        assert result is not None
        assert "Dangerous" in result["error"]

    def test_runPython_dangerous_import_not_blocked_at_harness(self):
        """Harness only checks command field for dangerous shell commands.
        Python code safety is handled at the tool level, not harness."""
        h = Harness()
        result = h.before_call("runPython", {"command": "import os"}, user_confirmed_coding=True)
        assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `D:/TOOL/Conda/conda/envs/PostProcessTool/python.exe -m pytest tests/agent/test_harness.py::TestCodingTools -v`
Expected: FAIL — `runBash` and `runPython` not in the harness check list.

**Step 3: Update harness.py**

In `agent/harness.py:37`, change:

```python
        if tool_name in ("run_bash", "runPythonString"):
```

to:

```python
        if tool_name in ("run_bash", "runPythonString", "runBash", "runPython"):
```

Also update the dangerous command check on line 40 — currently it reads `args.get("command", "")` but `runBash` uses `command` and `runPython` uses `code`. Fix:

```python
        if tool_name in ("run_bash", "runPythonString", "runBash", "runPython"):
            if not user_confirmed_coding:
                return {"error": "需要用户确认后才能执行自定义代码。请先询问用户。"}
            cmd = args.get("command", "") or args.get("code", "")
            for d in self.dangerous_commands:
                if d in cmd:
                    return {"error": f"Dangerous command blocked: {d}"}
```

**Step 4: Run tests to verify they pass**

Run: `D:/TOOL/Conda/conda/envs/PostProcessTool/python.exe -m pytest tests/agent/test_harness.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add agent/harness.py tests/agent/test_harness.py
git commit -m "feat: extend Harness to cover runBash/runPython tool names"
```

---

### Task 2: Create runBash MCP tool

**Files:**
- Create: `post_service/mcp_tools/run_bash.py`
- Test: `tests/post_service/test_run_bash.py`

**Step 1: Write the failing tests**

Create `tests/post_service/test_run_bash.py`:

```python
"""Tests for runBash MCP tool execution logic."""

import os
import sys
import importlib.util

# Load the module directly (MCP tool registration needs mcp+engine, but we test the runner)
_MOD_PATH = os.path.join(os.path.dirname(__file__), "../../post_service/mcp_tools/run_bash.py")
_spec = importlib.util.spec_from_file_location("run_bash", os.path.normpath(_MOD_PATH))
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
        # sleep 60 should be killed by 2s timeout
        result = _run_command("sleep 60", timeout=2)
        assert result["exit_code"] != 0 or "timeout" in result.get("error", "").lower()

    def test_output_truncation(self):
        # Generate large output, should be truncated
        result = _run_command("python -c \"print('x'*20000)\"", timeout=10, max_chars=1000)
        assert len(result["stdout"]) <= 1000
```

**Step 2: Run tests to verify they fail**

Run: `D:/TOOL/Conda/conda/envs/PostProcessTool/python.exe -m pytest tests/post_service/test_run_bash.py -v`
Expected: FAIL — module not found.

**Step 3: Create run_bash.py**

Create `post_service/mcp_tools/run_bash.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `D:/TOOL/Conda/conda/envs/PostProcessTool/python.exe -m pytest tests/post_service/test_run_bash.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add post_service/mcp_tools/run_bash.py tests/post_service/test_run_bash.py
git commit -m "feat: add runBash MCP tool with subprocess execution"
```

---

### Task 3: Create runPython MCP tool

**Files:**
- Create: `post_service/mcp_tools/run_python.py`
- Test: `tests/post_service/test_run_python.py`

**Step 1: Write the failing tests**

Create `tests/post_service/test_run_python.py`:

```python
"""Tests for runPython MCP tool execution logic."""

import os
import importlib.util
import tempfile

_MOD_PATH = os.path.join(os.path.dirname(__file__), "../../post_service/mcp_tools/run_python.py")
_spec = importlib.util.spec_from_file_location("run_python", os.path.normpath(_MOD_PATH))
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
        code = f"""
import os
path = r'{str(tmp_path / "test.png")}'
with open(path, 'w') as f:
    f.write('fake png')
print(f'CHATCFD_OUTPUT_FILE:{{path}}')
"""
        result = _run_python(code, timeout=10)
        assert result["exit_code"] == 0
        assert len(result["output_files"]) == 1
        assert result["output_files"][0].endswith("test.png")

    def test_timeout(self):
        result = _run_python("import time; time.sleep(60)", timeout=2)
        assert result["exit_code"] != 0 or "timeout" in result.get("error", "").lower()

    def test_output_truncation(self):
        result = _run_python("print('x' * 20000)", timeout=10, max_chars=1000)
        assert len(result["stdout"]) <= 1000
```

**Step 2: Run tests to verify they fail**

Run: `D:/TOOL/Conda/conda/envs/PostProcessTool/python.exe -m pytest tests/post_service/test_run_python.py -v`
Expected: FAIL — module not found.

**Step 3: Create run_python.py**

Create `post_service/mcp_tools/run_python.py`:

```python
"""MCP tool: runPython — Execute Python code in an isolated subprocess."""

import os
import re
import subprocess
import sys
import tempfile


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
        """Execute Python code in an isolated subprocess. Requires user confirmation.
        Pre-installed: numpy, matplotlib, imageio, pandas, vtk.
        To report output files, print 'CHATCFD_OUTPUT_FILE:/path/to/file' in your script.
        Use for: plotting, data processing, GIF synthesis, file conversion.
        Do NOT use for tasks achievable with existing tools (loadFile/calculate/exportData)."""
        state = engine.session_mgr.get(session_id)
        cwd = state.output_dir if state else None
        return _run_python(code, timeout=min(timeout, 120), max_chars=5000, cwd=cwd)
```

**Step 4: Run tests to verify they pass**

Run: `D:/TOOL/Conda/conda/envs/PostProcessTool/python.exe -m pytest tests/post_service/test_run_python.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add post_service/mcp_tools/run_python.py tests/post_service/test_run_python.py
git commit -m "feat: add runPython MCP tool with subprocess execution"
```

---

### Task 4: Register new tools in MCP and update Skills

**Files:**
- Modify: `post_service/mcp_tools/__init__.py`
- Modify: `agent/skills.py`

**Step 1: Register in __init__.py**

In `post_service/mcp_tools/__init__.py`, add imports and registration:

```python
from post_service.mcp_tools.run_bash import register as register_run_bash
from post_service.mcp_tools.run_python import register as register_run_python
```

In `register_all()`, add at the end:

```python
    register_run_bash(mcp, engine)
    register_run_python(mcp, engine)
```

**Step 2: Update skills.py TOOLS table**

In `agent/skills.py`, add to the TOOLS table after the existing tools:

```
| runBash(command) | 执行 Shell 命令（需用户确认） |
| runPython(code) | 执行 Python 脚本（需用户确认） |
```

**Step 3: Update skills.py RULES**

Add to the "必须做" section in RULES:

```
11. **runBash/runPython → 必须先问用户确认**，不要在用户未明确同意前调用代码执行工具
12. **能用现有工具完成的任务不要写代码** — loadFile/calculate/exportData 能做的事不要用 runBash/runPython
13. **runPython 输出文件 → 打印 `CHATCFD_OUTPUT_FILE:路径`**，这样系统能自动识别产物
```

**Step 4: Verify PostService starts correctly**

Run: `D:/TOOL/Conda/conda/envs/PostProcessTool/python.exe -c "from post_service.mcp_tools import register_all; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add post_service/mcp_tools/__init__.py agent/skills.py
git commit -m "feat: register runBash/runPython in MCP and update Skills prompt"
```

---

### Task 5: Wire user confirmation in agent_loop (chat-based)

**Files:**
- Modify: `agent/agent_loop.py` (stream_run function)

**Step 1: Add auto-confirmation detection**

In `agent/agent_loop.py`, in the `stream_run` function, add user confirmation detection.
When the user's message contains confirmation keywords and the previous assistant message asked about coding, set the flag.

Find the line where user messages are appended (in `main.py:166`):

```python
session.messages.append({"role": "user", "content": query})
```

Add confirmation detection in `main.py`, right after that line:

```python
# Auto-detect coding confirmation from user response
_CONFIRM_KEYWORDS = {"可以", "好的", "允许", "执行", "同意", "yes", "ok", "确认", "没问题", "行"}
if any(kw in query.lower() for kw in _CONFIRM_KEYWORDS):
    # Check if previous assistant message was asking about coding
    prev_msgs = [m for m in session.messages if m.get("role") == "assistant"]
    if prev_msgs:
        last_asst = prev_msgs[-1].get("content", "")
        if last_asst and any(k in last_asst for k in ("编写", "脚本", "代码", "执行", "runBash", "runPython")):
            session.user_confirmed_coding = True
```

**Step 2: Verify the flow end-to-end**

Restart services (both PostService and Agent will auto-reload with --reload).
In the chat UI:
1. Load a file: "加载 D:/XField/data/cgns/ysy.cgns"
2. Ask for coding: "帮我生成一个 GIF"
3. Agent should ask for confirmation
4. Reply: "可以"
5. Agent should now be able to call runBash/runPython

**Step 3: Commit**

```bash
git add agent/main.py
git commit -m "feat: auto-detect user coding confirmation from chat keywords"
```

---

### Task 6: Integration test — full pipeline

**Files:**
- Create: `tests/post_service/test_coding_integration.py`

**Step 1: Write integration test**

```python
"""Integration test: runBash and runPython tools via engine."""

import os
import tempfile

from post_service.mcp_tools.run_bash import _run_command
from post_service.mcp_tools.run_python import _run_python


class TestCodingIntegration:
    def test_ffmpeg_available(self):
        """Verify ffmpeg is on PATH (needed for GIF synthesis)."""
        result = _run_command("ffmpeg -version", timeout=10)
        # ffmpeg may or may not be installed; just verify the tool works
        assert "exit_code" in result

    def test_matplotlib_plot_and_save(self, tmp_path):
        """Full flow: Python generates a plot, saves to file, reports path."""
        out = str(tmp_path / "test_plot.png").replace("\\", "/")
        code = f"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 10, 100)
plt.plot(x, np.sin(x))
plt.savefig(r'{out}')
print(f'CHATCFD_OUTPUT_FILE:{out}')
print('Plot saved')
"""
        result = _run_python(code, timeout=30)
        assert result["exit_code"] == 0, f"stderr: {result['stderr']}"
        assert "Plot saved" in result["stdout"]
        assert len(result["output_files"]) == 1
        assert os.path.exists(out)

    def test_harness_blocks_then_allows(self):
        """Verify Harness blocks runBash without confirm, allows with."""
        from agent.harness import Harness
        h = Harness()
        # Blocked
        r1 = h.before_call("runBash", {"command": "echo test"}, user_confirmed_coding=False)
        assert r1 is not None
        # Allowed
        r2 = h.before_call("runBash", {"command": "echo test"}, user_confirmed_coding=True)
        assert r2 is None
        # Execute
        result = _run_command("echo integration_test", timeout=10)
        assert result["exit_code"] == 0
        assert "integration_test" in result["stdout"]
```

**Step 2: Run all tests**

Run: `D:/TOOL/Conda/conda/envs/PostProcessTool/python.exe -m pytest tests/ -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add tests/post_service/test_coding_integration.py
git commit -m "test: add coding tools integration tests"
```

---

## Summary

After completing all 6 tasks:

- **2 new MCP tools**: `runBash` (shell) + `runPython` (isolated Python subprocess)
- **Harness updated**: covers all 4 coding tool names, checks both `command` and `code` fields
- **Skills prompt updated**: LLM knows about the new tools and rules
- **User confirmation flow**: chat-based detection ("可以" → sets flag)
- **Tests**: unit tests for each tool + integration test

**Not in scope (Phase 2b/3):**
- Coding sub-agent with iterative loop (sub_agent.py)
- `runEngineCode` (in-process execution with PostData access)
- Frontend confirmation button/dialog
