"""Offline analysis of conversation traces dumped by insight_log.dump_trace.

Reads `.chatcfd/traces/*.json`, extracts one row per user turn, and writes
a CSV. A heuristic flag marks turns whose *next* user message looks like
a correction ("不对", "再画一次", ...) — those are candidate pain points
for tool description / granularity review.

Usage:
    python tools/analyze_traces.py
    python tools/analyze_traces.py --traces-dir .chatcfd/traces --out turns.csv
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict


CORRECTION_PATTERNS = [
    r"不对", r"错了?", r"不是这个", r"不是这样", r"我想要的?是", r"我要的?是",
    r"应该是", r"不要这个", r"不要这样", r"换一个", r"换种", r"再来一次",
    r"再画一次", r"再跑一次", r"重新", r"重画", r"重跑",
    # English (tentative)
    r"\bwrong\b", r"\bnot (what|this)\b", r"\bredo\b", r"\bi meant\b",
    r"\bshould be\b", r"\bactually\b,",
]
CORRECTION_RE = re.compile("|".join(CORRECTION_PATTERNS), re.IGNORECASE)


def _shorten(text, limit=200):
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\r", " ").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _tool_label(tc):
    """Make a compact label for a tool_call dict (OpenAI format)."""
    fn = tc.get("function", {}) or {}
    name = fn.get("name", "?")
    args_raw = fn.get("arguments", "")
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
    except json.JSONDecodeError:
        args = {}
    # Pull out the most discriminating param per tool to make the label useful.
    if name == "calculate":
        m = args.get("method", "")
        return f"calculate({m})" if m else "calculate"
    if name == "getMethodTemplate":
        return f"getMethodTemplate({args.get('method', '')})"
    return name


def extract_turns(trace_path):
    """Yield one dict per user turn found in this trace file."""
    with open(trace_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    conv_id = payload.get("session_id", os.path.basename(trace_path))
    messages = payload.get("messages", [])

    turns = []
    current = None
    turn_idx = 0

    for msg in messages:
        role = msg.get("role")
        if role == "user":
            if current is not None:
                turns.append(current)
            turn_idx += 1
            current = {
                "conv_id": conv_id,
                "turn_idx": turn_idx,
                "user_query": msg.get("content", "") or "",
                "tools_called": [],
                "assistant_reply": "",
            }
        elif role == "assistant" and current is not None:
            # Accumulate tool_calls and final text
            for tc in msg.get("tool_calls", []) or []:
                current["tools_called"].append(_tool_label(tc))
            content = msg.get("content") or ""
            if content:
                # Assistant may emit text across multiple messages in a turn.
                current["assistant_reply"] = (
                    (current["assistant_reply"] + " " + content).strip()
                )
        # tool/system roles are ignored at this level (we care about user/asst)
    if current is not None:
        turns.append(current)

    # Second pass: attach next_user_query + correction flag
    for i, t in enumerate(turns):
        nxt = turns[i + 1]["user_query"] if i + 1 < len(turns) else ""
        t["next_user_query"] = nxt
        t["correction_flag"] = bool(nxt and CORRECTION_RE.search(nxt))

    return turns


def write_csv(rows, out_path):
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fields = [
        "conv_id", "turn_idx", "user_query", "tools_called",
        "assistant_reply", "next_user_query", "correction_flag", "notes",
    ]
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({
                "conv_id": r["conv_id"],
                "turn_idx": r["turn_idx"],
                "user_query": _shorten(r["user_query"], 300),
                "tools_called": " | ".join(r["tools_called"]),
                "assistant_reply": _shorten(r["assistant_reply"], 300),
                "next_user_query": _shorten(r["next_user_query"], 200),
                "correction_flag": "Y" if r["correction_flag"] else "",
                "notes": "",
            })


def print_summary(rows):
    n_turns = len(rows)
    n_correction = sum(1 for r in rows if r["correction_flag"])
    print(f"Total user turns: {n_turns}")
    print(f"Suspected correction turns: {n_correction} "
          f"({100 * n_correction / n_turns:.1f}%)" if n_turns else "")
    print()

    # Per-tool: how often called, how often followed by correction
    tool_calls = Counter()
    tool_followed_by_correction = Counter()
    for r in rows:
        for label in r["tools_called"]:
            tool_calls[label] += 1
            if r["correction_flag"]:
                tool_followed_by_correction[label] += 1

    if tool_calls:
        print(f"{'tool':<32} {'calls':>6} {'followed_by_correction':>22}")
        print("-" * 62)
        for tool, n in tool_calls.most_common():
            fc = tool_followed_by_correction[tool]
            pct = (100 * fc / n) if n else 0
            print(f"{tool:<32} {n:>6} {fc:>12} ({pct:>4.0f}%)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--traces-dir", default=".chatcfd/traces",
                   help="Directory with trace JSON files")
    p.add_argument("--out", default=".chatcfd/turns.csv",
                   help="Output CSV path")
    args = p.parse_args()

    if not os.path.isdir(args.traces_dir):
        print(f"No traces dir: {args.traces_dir}", file=sys.stderr)
        return 1

    all_rows = []
    files = sorted(f for f in os.listdir(args.traces_dir) if f.endswith(".json"))
    for name in files:
        path = os.path.join(args.traces_dir, name)
        try:
            all_rows.extend(extract_turns(path))
        except Exception as e:
            print(f"[warn] skip {name}: {e}", file=sys.stderr)

    if not all_rows:
        print("No user turns found.")
        return 0

    write_csv(all_rows, args.out)
    print(f"Wrote {len(all_rows)} rows to {args.out}\n")
    print_summary(all_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
