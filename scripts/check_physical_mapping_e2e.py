"""End-to-end sanity check for the SimGraph2 physical mapping migration.

Loads a real CGNS file through PostEngine and prints:
- solver_id detection
- every scalar's (raw_name -> standard_name/display_name/unit/confidence)
- a representative get_scalar() round-trip using both raw and standard names
"""

from __future__ import annotations

import io
import json
import os
import sys
import time

# Force UTF-8 on Windows GBK consoles so Chinese display_names print cleanly.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from post_service.engine import PostEngine  # noqa: E402


CANDIDATES = [
    os.path.join(ROOT, "tests", "data", "X37b", "x37b-02.cgns"),
    os.path.join(ROOT, "tests", "data", "ysy", "ysy.cgns"),
]


def main() -> int:
    target = next((p for p in CANDIDATES if os.path.isfile(p)), None)
    if target is None:
        print("[FAIL] no test CGNS file available under tests/data/")
        return 2

    print(f"[RUN] loading {target}")
    engine = PostEngine()
    t0 = time.time()
    result = engine.load_file("e2e-check", target)
    print(f"[RUN] load_file finished in {time.time() - t0:.2f}s")

    if "error" in result:
        print(f"[FAIL] load_file returned error: {result['error']}")
        return 1

    print("\n=== solver_id detection ===")
    print(f"solver_id = {result.get('solver_id')!r}")

    print("\n=== zone / scalar summary ===")
    for zone in result.get("zones", []):
        print(f"\n- zone {zone['name']!r}  points={zone['point_count']}  cells={zone['cell_count']}")
        for sc in zone["scalars"]:
            extras = {k: v for k, v in sc.items() if k not in ("raw_name",)}
            print(f"    {sc['raw_name']!r:30s} -> {json.dumps(extras, ensure_ascii=False)}")

    # Try a round-trip via get_scalar with both a raw and a standard name.
    print("\n=== get_scalar round-trip ===")
    state = engine.session_mgr.get("e2e-check")
    pd = state.post_data
    first_zone = pd.get_zones()[0]
    first_raw = pd.get_scalar_names(first_zone)[0]
    try:
        arr = pd.get_scalar(first_zone, first_raw)
        print(f"[OK] get_scalar({first_zone!r}, {first_raw!r}) -> shape={arr.shape}, dtype={arr.dtype}")
    except Exception as e:
        print(f"[FAIL] get_scalar raw-name lookup: {e}")
        return 1

    # Try standard-name lookup if we recognised anything.
    for sc in pd.get_summary()["zones"][0]["scalars"]:
        std = sc.get("standard_name")
        if std:
            try:
                arr = pd.get_scalar(first_zone, std)
                print(f"[OK] get_scalar({first_zone!r}, {std!r}) -> shape={arr.shape} (mapped from raw {sc['raw_name']!r})")
            except Exception as e:
                print(f"[FAIL] get_scalar standard-name lookup ({std!r}): {e}")
                return 1
            break
    else:
        print("[WARN] no scalar had a standard_name — mapping may be too narrow for this file")

    print("\n[OK] end-to-end check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
