"""LLM behavior test.

Drives agent_loop.run() with predefined queries and verifies LLM made the
correct tool calls. Requires:
  - PostService running on http://127.0.0.1:8001
  - DASHSCOPE_API_KEY (or compatible) in env or .chatcfd/settings.json

Usage:
    conda activate PostProcessTool
    python -m tools.llm_behavior_test            # all tests
    python -m tools.llm_behavior_test --quick    # only critical tests
    python -m tools.llm_behavior_test --verbose  # print full LLM output
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

# Load persisted settings (api key, model)
_SETTINGS_FILE = os.path.join(ROOT, ".chatcfd", "settings.json")
if os.path.isfile(_SETTINGS_FILE):
    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
            _s = json.load(f)
        if _s.get("api_key"):
            os.environ.setdefault("OPENAI_API_KEY", _s["api_key"])
            os.environ.setdefault("DASHSCOPE_API_KEY", _s["api_key"])
        if _s.get("api_base"):
            os.environ.setdefault("OPENAI_API_BASE", _s["api_base"])
            os.environ.setdefault("LLM_API_BASE", _s["api_base"])
    except Exception:
        pass

from agent import agent_loop
from agent.harness import Harness
from agent.mcp_client import MCPClient, MCPClientPool
from agent.session import AgentSession

MODEL = os.environ.get("MODEL_ID", "openai/qwen-plus")
MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8001/mcp/sse")
DATA_DIR = "D:/XField/data/cgns"


def _c(text, color):
    codes = {"green": "\033[92m", "red": "\033[91m", "yellow": "\033[93m", "cyan": "\033[96m", "reset": "\033[0m"}
    return f"{codes.get(color, '')}{text}{codes['reset']}"


def _extract_tool_calls(session: AgentSession) -> list[dict]:
    """Extract all tool calls made in this session."""
    calls = []
    for msg in session.messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except Exception:
                    args = {}
                calls.append({"name": fn.get("name", ""), "args": args})
    return calls


def _has_call(calls, name, **arg_predicates) -> bool:
    """Check if any tool call matches name and arg predicates."""
    for c in calls:
        if c["name"] != name:
            continue
        ok = True
        for k, predicate in arg_predicates.items():
            if k not in c["args"]:
                ok = False
                break
            v = c["args"][k]
            if callable(predicate):
                if not predicate(v):
                    ok = False
                    break
            elif v != predicate:
                ok = False
                break
        if ok:
            return True
    return False


class LLMTester:
    def __init__(self, verbose=False):
        self.mcp_pool = MCPClientPool()
        self.harness = Harness()
        self.results = []
        self.verbose = verbose

    def setup(self):
        """Connect to PostService MCP."""
        print(_c("Connecting to MCP at", "cyan"), MCP_URL)
        self.mcp_pool.add_client(MCPClient(name="post_service", transport="sse", url=MCP_URL))
        try:
            self.mcp_pool.load_all_tools()
        except Exception as e:
            print(_c(f"FATAL: Cannot connect to PostService: {e}", "red"))
            print(_c(f"Make sure PostService is running on port 8001", "yellow"))
            sys.exit(1)
        print(_c(f"Loaded {len(self.mcp_pool._tool_route)} MCP tools", "green"))

    def _new_session(self, preload_file=None):
        """Create a fresh session, optionally pre-load a file."""
        session = AgentSession("test")
        if preload_file:
            # Pre-load via direct MCP call so PostService has the file
            raw = self.mcp_pool.call_tool("loadFile", {"file_path": preload_file, "session_id": "test"})
            session.loaded_file_path = preload_file
            # Inject a fake history so LLM knows the file is loaded
            try:
                summary = json.loads(raw)
                zones = [z.get("name") for z in summary.get("zones", [])][:5]
                session.messages.append({
                    "role": "user", "content": f"加载 {preload_file}",
                })
                session.messages.append({
                    "role": "assistant",
                    "content": (
                        f"已加载 {preload_file}：{summary.get('zone_count', 0)} 个 zone "
                        f"({', '.join(zones)})，{summary.get('total_cells', 0)} cells。"
                    ),
                })
            except Exception:
                pass
        return session

    def _ask(self, session, query, allow_coding=False):
        """Send a query to LLM and return all tool calls made."""
        if allow_coding:
            session.user_confirmed_coding = True
        session.messages.append({"role": "user", "content": query})
        result = agent_loop.run(
            session, self.mcp_pool, self.harness, model=MODEL,
            max_rounds=8, mcp_session_id="test",  # match pre-load session_id
        )
        calls = _extract_tool_calls(session)
        if self.verbose:
            print(_c("  LLM final reply:", "cyan"), result.get("content", "")[:200])
            print(_c(f"  Tool calls made ({len(calls)}):", "cyan"))
            for c in calls:
                print(f"    - {c['name']}({json.dumps(c['args'], ensure_ascii=False)[:100]})")
        return calls, result

    def _run(self, name, func, critical=False):
        marker = " *" if critical else ""
        print(f"\n{_c('>', 'cyan')} {name}{marker}")
        t0 = time.perf_counter()
        try:
            ok, msg = func()
            elapsed = time.perf_counter() - t0
            color = "green" if ok else "red"
            status = "PASS" if ok else "FAIL"
            print(f"  {_c(status, color)} ({elapsed:.1f}s) — {msg}")
            self.results.append((name, ok, elapsed, msg))
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"  {_c('ERROR', 'red')} ({elapsed:.1f}s) — {type(e).__name__}: {e}")
            self.results.append((name, False, elapsed, str(e)))

    # === Test cases ===

    def test_load_explicit_path(self):
        """LLM should call loadFile with the exact path."""
        session = self._new_session()
        calls, _ = self._ask(session, f"加载 {DATA_DIR}/ysy.cgns")
        if _has_call(calls, "loadFile", file_path=lambda v: "ysy.cgns" in v):
            return True, f"loadFile called with ysy.cgns ({len(calls)} total calls)"
        return False, f"loadFile not called or wrong path. Calls: {[c['name'] for c in calls]}"

    def test_load_fuzzy_search(self):
        """LLM should listFiles(recursive,keyword) before loadFile when name is partial."""
        session = self._new_session()
        calls, _ = self._ask(session, f"加载 {DATA_DIR} 下的 x37b 文件")
        listed = _has_call(calls, "listFiles", keyword=lambda v: "x37b" in str(v).lower())
        loaded = _has_call(calls, "loadFile", file_path=lambda v: "x37b" in v.lower())
        if listed and loaded:
            return True, "listFiles → loadFile chain executed"
        msg = []
        if not listed: msg.append("missing listFiles with keyword=x37b")
        if not loaded: msg.append("missing loadFile")
        return False, "; ".join(msg) + f". Calls: {[c['name'] for c in calls]}"

    def test_statistics(self):
        """After loading, asking for statistics should call calculate(method=statistics)."""
        session = self._new_session(preload_file=f"{DATA_DIR}/ysy.cgns")
        calls, _ = self._ask(session, "给我 solid zone 的标量统计")
        if _has_call(calls, "calculate", method="statistics"):
            return True, "calculate(method=statistics) called"
        return False, f"Wrong tool. Calls: {[(c['name'], c['args'].get('method', '')) for c in calls]}"

    def test_quality_check(self):
        """Asking '检查质量' should call calculate(method=check)."""
        session = self._new_session(preload_file=f"{DATA_DIR}/ysy.cgns")
        calls, _ = self._ask(session, "检查一下这个仿真有没有问题")
        if _has_call(calls, "calculate", method="check"):
            return True, "calculate(method=check) called"
        return False, f"Wrong method. Calls: {[(c['name'], c['args'].get('method', '')) for c in calls]}"

    def test_slice_with_gif(self):
        """Asking for GIF should call slice with output_images=True."""
        session = self._new_session(preload_file=f"{DATA_DIR}/ysy.cgns")
        calls, _ = self._ask(session, "沿X方向切5个切片用Pressure着色，合成GIF动画")
        # Check for slice call
        slice_calls = [c for c in calls if c["name"] == "calculate" and c["args"].get("method") == "slice"]
        if not slice_calls:
            return False, f"No slice call. Calls: {[(c['name'], c['args'].get('method', '')) for c in calls]}"
        # Parse params (string JSON)
        for sc in slice_calls:
            params = sc["args"].get("params", "{}")
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except Exception:
                    params = {}
            if params.get("output_images") in (True, "true", "True", 1):
                return True, "slice called with output_images=True"
        return False, f"slice called but output_images not set. Params: {[c['args'].get('params') for c in slice_calls]}"

    def test_probe_line(self):
        """Asking for distribution curve should call probe_line."""
        session = self._new_session(preload_file=f"{DATA_DIR}/ysy.cgns")
        calls, _ = self._ask(session, "给我 solid zone 的压力沿 X 方向分布曲线")
        if _has_call(calls, "calculate", method="probe_line"):
            return True, "calculate(method=probe_line) called"
        return False, f"Wrong method. Calls: {[(c['name'], c['args'].get('method', '')) for c in calls]}"

    def test_no_coding_for_simple_task(self):
        """LLM should NOT use runPython/runBash for tasks doable with built-in tools."""
        session = self._new_session(preload_file=f"{DATA_DIR}/ysy.cgns")
        calls, _ = self._ask(session, "看下 solid zone 有几种网格类型", allow_coding=True)
        coding = _has_call(calls, "runPython") or _has_call(calls, "runBash")
        if not coding:
            return True, "Did not invoke coding tools (correctly used loadFile result)"
        return False, "LLM unnecessarily invoked coding tools for a simple cell_types lookup"

    def run(self, quick=False):
        print(_c("=" * 70, "cyan"))
        print(_c("ChatCFD LLM Behavior Test", "cyan"))
        print(_c(f"Model: {MODEL}", "cyan"))
        print(_c("=" * 70, "cyan"))

        self.setup()

        critical = [
            ("Load with explicit path", self.test_load_explicit_path),
            ("Load with fuzzy name (recursive search)", self.test_load_fuzzy_search),
            ("Statistics on zone", self.test_statistics),
            ("Quality check", self.test_quality_check),
            ("Slice + GIF (one-step)", self.test_slice_with_gif),
        ]
        extra = [
            ("Probe line distribution", self.test_probe_line),
            ("Don't over-use coding tools", self.test_no_coding_for_simple_task),
        ]

        for name, fn in critical:
            self._run(name, fn, critical=True)
        if not quick:
            for name, fn in extra:
                self._run(name, fn)

        # Summary
        print()
        print(_c("=" * 70, "cyan"))
        print(_c("SUMMARY", "cyan"))
        print(_c("=" * 70, "cyan"))
        passed = sum(1 for _, ok, _, _ in self.results if ok)
        failed = len(self.results) - passed
        total_time = sum(t for _, _, t, _ in self.results)
        print(f"Total: {len(self.results)}   {_c(f'Passed: {passed}', 'green')}   "
              f"{_c(f'Failed: {failed}', 'red' if failed else 'green')}   Time: {total_time:.1f}s")
        if failed:
            print(f"\n{_c('Failed tests:', 'red')}")
            for name, ok, _, msg in self.results:
                if not ok:
                    print(f"  X {name}: {msg}")
        return failed == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    tester = LLMTester(verbose=args.verbose)
    success = tester.run(quick=args.quick)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
