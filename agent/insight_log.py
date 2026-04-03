"""InsightLog — JSONL query logging for product iteration."""

import json
import os
import time


def log_query(log_dir, session_id, user_input, resolution, tools_called=None):
    """Append one insight entry to the JSONL log file."""
    os.makedirs(log_dir, exist_ok=True)
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_id": session_id,
        "user_input": user_input,
        "resolution": resolution,
        "tools_called": tools_called or [],
    }
    path = os.path.join(log_dir, "insight_log.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
