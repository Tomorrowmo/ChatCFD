"""Profile loadFile for each .cgns in a directory.

For each file:
  - prints a real-time trace of post_service.* function entries
  - measures wall-clock time
  - reports cProfile stats: total call count, top functions by cumulative time

Usage:
    conda activate PostProcessTool
    python -m tools.profile_loadfile [directory] [--max-size-gb N] [--no-trace]

Default directory: D:/XField/data/cgns
"""
import argparse
import cProfile
import os
import pstats
import sys
import time
from io import StringIO

# Ensure project root on path so `post_service` imports work
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from post_service.engine import PostEngine

# Modules whose Python function calls we want to trace in real time
TRACE_PREFIXES = (
    "post_service.engine",
    "post_service.session",
    "post_service.post_data",
    "post_service.archive",
    "post_service.algorithm_registry",
)

_trace_depth = 0


def _make_tracer(start_time):
    """Build a trace function that prints entry into post_service.* code only."""
    def tracer(frame, event, arg):
        global _trace_depth
        if event != "call":
            return None  # don't trace lines/returns to keep noise low
        mod = frame.f_globals.get("__name__", "")
        if not mod.startswith("post_service"):
            return None
        # Only trace prefixes we care about (skip e.g. mcp_tools)
        if not any(mod.startswith(p) for p in TRACE_PREFIXES):
            return None
        func = frame.f_code.co_name
        if func.startswith("_") and func not in ("__init__", "_get_block", "_resolve_name"):
            return None  # skip internals to keep output readable
        elapsed = time.perf_counter() - start_time
        indent = "  " * _trace_depth
        print(f"  [{elapsed:7.2f}s] {indent}→ {mod}.{func}()", flush=True)
        _trace_depth += 1

        def returner(frame_, event_, arg_):
            global _trace_depth
            if event_ == "return":
                _trace_depth = max(0, _trace_depth - 1)
            return returner
        return returner
    return tracer


def profile_one(engine: PostEngine, file_path: str, session_id: str, enable_trace: bool):
    """Run engine.load_file under cProfile + optional sys.settrace, return metrics."""
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    print(f"\n{'=' * 70}")
    print(f"FILE: {file_path}")
    print(f"SIZE: {size_mb:.1f} MB")
    print(f"{'=' * 70}")

    profiler = cProfile.Profile()
    start = time.perf_counter()

    if enable_trace:
        global _trace_depth
        _trace_depth = 0
        sys.settrace(_make_tracer(start))

    profiler.enable()
    try:
        result = engine.load_file(session_id, file_path)
    finally:
        profiler.disable()
        if enable_trace:
            sys.settrace(None)

    elapsed = time.perf_counter() - start

    # Summarize cProfile output
    stream = StringIO()
    stats = pstats.Stats(profiler, stream=stream).sort_stats("cumulative")
    total_calls = stats.total_calls
    primitive_calls = stats.prim_calls

    # Top 15 functions by cumulative time (filter out cProfile/builtins noise)
    print(f"\nRESULT: ", end="")
    if isinstance(result, dict) and result.get("error"):
        print(f"ERROR — {result['error']}")
    else:
        zone_count = result.get("zone_count", "?")
        total_cells = result.get("total_cells", "?")
        frame_count = result.get("frame_count", "?")
        print(f"{zone_count} zones, {total_cells} cells, {frame_count} frame(s)")

    print(f"\nMETRICS:")
    print(f"  wall_time:       {elapsed:.2f} s")
    print(f"  total_calls:     {total_calls:,}  (Python function calls — the 'token' count)")
    print(f"  primitive_calls: {primitive_calls:,}  (excludes recursion)")
    print(f"  throughput:      {size_mb / elapsed:.1f} MB/s")

    print(f"\nTOP 15 FUNCTIONS BY CUMULATIVE TIME:")
    stats.print_stats(15)
    # Pull the table portion out of the buffer
    output = stream.getvalue()
    lines = output.split("\n")
    # The actual table starts a few lines in; print everything after the header
    in_table = False
    for line in lines:
        if "ncalls" in line and "tottime" in line:
            in_table = True
        if in_table:
            print("  " + line)

    return {
        "file": os.path.basename(file_path),
        "size_mb": round(size_mb, 1),
        "wall_time_s": round(elapsed, 2),
        "total_calls": total_calls,
        "primitive_calls": primitive_calls,
        "throughput_mbps": round(size_mb / elapsed, 1) if elapsed > 0 else 0,
        "error": result.get("error") if isinstance(result, dict) and result.get("error") else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="D:/XField/data/cgns",
                        help="Directory containing .cgns files")
    parser.add_argument("--max-size-gb", type=float, default=10.0,
                        help="Skip files larger than this (default: 10 GB)")
    parser.add_argument("--no-trace", action="store_true",
                        help="Disable real-time function call tracing")
    parser.add_argument("--only", nargs="+", default=None,
                        help="Only profile files whose name matches any of these substrings")
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"ERROR: directory not found: {args.directory}")
        return 1

    files = []
    for f in sorted(os.listdir(args.directory)):
        if not f.lower().endswith(".cgns"):
            continue
        full = os.path.normpath(os.path.join(args.directory, f)).replace("\\", "/")
        size_gb = os.path.getsize(full) / (1024 ** 3)
        if size_gb > args.max_size_gb:
            print(f"[skip] {f} ({size_gb:.2f} GB > {args.max_size_gb} GB limit)")
            continue
        if args.only and not any(s in f for s in args.only):
            continue
        files.append(full)

    if not files:
        print("No .cgns files to profile.")
        return 1

    print(f"Profiling {len(files)} file(s) from {args.directory}")
    print(f"Trace mode: {'OFF' if args.no_trace else 'ON (post_service.* function entries)'}")

    # One engine per file to avoid cache effects across files; algorithms_dir not needed
    results = []
    for i, fp in enumerate(files):
        engine = PostEngine()  # fresh engine each time
        session_id = f"profile_{i}"
        try:
            metrics = profile_one(engine, fp, session_id, enable_trace=not args.no_trace)
            results.append(metrics)
        except Exception as e:
            print(f"\n[FATAL] {fp}: {e}")
            results.append({"file": os.path.basename(fp), "error": str(e)})

    # Final summary table
    print(f"\n\n{'=' * 70}")
    print(f"SUMMARY")
    print(f"{'=' * 70}")
    print(f"{'file':<32} {'size MB':>10} {'time s':>10} {'calls':>14} {'MB/s':>8}")
    print("-" * 76)
    for r in results:
        if r.get("error"):
            print(f"{r['file']:<32} ERROR: {r['error'][:40]}")
            continue
        print(f"{r['file']:<32} {r['size_mb']:>10.1f} {r['wall_time_s']:>10.2f} "
              f"{r['total_calls']:>14,} {r['throughput_mbps']:>8.1f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
