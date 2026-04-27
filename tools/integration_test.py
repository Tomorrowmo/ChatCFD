"""End-to-end backend integration test.

Runs through the test cases from docs/test-conversations.md that don't need LLM.
Calls engine.load_file + calculate(method=...) directly and verifies outputs.

Usage:
    conda activate PostProcessTool
    python -m tools.integration_test
    python -m tools.integration_test --quick   # only critical tests
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from post_service.engine import PostEngine

# Test data
DATA_DIR = "D:/XField/data/cgns"
FILE_YSY = f"{DATA_DIR}/ysy.cgns"
FILE_X37B = f"{DATA_DIR}/x37b-02.cgns"
FILE_J20 = f"{DATA_DIR}/j20_1.cgns"
FILE_AOA = f"{DATA_DIR}/AOA10.5_mach1.2.cgns"


# Color output
def _c(text, color):
    codes = {"green": "\033[92m", "red": "\033[91m", "yellow": "\033[93m", "cyan": "\033[96m", "reset": "\033[0m"}
    return f"{codes.get(color, '')}{text}{codes['reset']}"


class TestRunner:
    def __init__(self):
        self.engine = PostEngine(algorithms_dir=os.path.join(ROOT, "post_service/algorithms"))
        self.results = []

    def _run(self, name, func, critical=False):
        marker = " *" if critical else ""
        print(f"\n{_c('>', 'cyan')} {name}{marker}")
        t0 = time.perf_counter()
        try:
            ok, msg = func()
            elapsed = time.perf_counter() - t0
            status = "PASS" if ok else "FAIL"
            color = "green" if ok else "red"
            print(f"  {_c(status, color)} ({elapsed:.2f}s) — {msg}")
            self.results.append((name, ok, elapsed, msg, critical))
            return ok
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"  {_c('ERROR', 'red')} ({elapsed:.2f}s) — {type(e).__name__}: {e}")
            self.results.append((name, False, elapsed, str(e), critical))
            return False

    # --- Test cases ---

    def test_load_ysy(self):
        result = self.engine.load_file("test", FILE_YSY)
        if "error" in result:
            return False, result["error"]
        n_zones = result.get("zone_count", 0)
        n_cells = result.get("total_cells", 0)
        has_cell_types = any("cell_types" in z for z in result.get("zones", []))
        if not has_cell_types:
            return False, "Missing cell_types in zones"
        return True, f"{n_zones} zones, {n_cells} cells, has cell_types"

    def test_load_x37b(self):
        result = self.engine.load_file("test", FILE_X37B)
        if "error" in result:
            return False, result["error"]
        return True, f"{result.get('zone_count', 0)} zones, {result.get('total_cells', 0)} cells"

    def test_recursive_search(self):
        result = self.engine.list_files(DATA_DIR, suffix=".cgns", keyword="x37b", recursive=True)
        if "error" in result:
            return False, result["error"]
        files = result.get("files", [])
        if not files:
            return False, "No files matched 'x37b' keyword"
        if not any("x37b" in f.lower() for f in files):
            return False, f"Match wrong: {files}"
        return True, f"Found {len(files)} files: {os.path.basename(files[0])}"

    def test_statistics(self):
        # Load first
        self.engine.load_file("test_stats", FILE_YSY)
        result = self.engine.calculate("test_stats", "statistics", {}, "solid")
        if "error" in result:
            return False, result["error"]
        data = result.get("data", {})
        if not data:
            return False, "No statistics data"
        return True, f"{len(data)} scalars stat'd, e.g. {list(data.keys())[0]}"

    def test_check(self):
        self.engine.load_file("test_check", FILE_YSY)
        result = self.engine.calculate("test_check", "check", {}, "")
        if "error" in result:
            return False, result["error"]
        data = result.get("data", {})
        return True, f"Checked {data.get('zones_checked', 0)} zones, {data.get('total_issues', 0)} issues"

    def test_slice_basic(self):
        self.engine.load_file("test_slice", FILE_YSY)
        result = self.engine.calculate("test_slice", "slice",
                                       {"n_slices": 5, "direction": 0, "scalar": "Pressure"}, "solid")
        if "error" in result:
            return False, result["error"]
        out_file = result.get("data", {}).get("output_file", "")
        if not os.path.exists(out_file):
            return False, f"Output file missing: {out_file}"
        return True, f"5 planes, VTP at {os.path.basename(out_file)}"

    def test_slice_with_gif(self):
        self.engine.load_file("test_gif", FILE_YSY)
        result = self.engine.calculate("test_gif", "slice", {
            "n_slices": 5, "direction": 0, "scalar": "Pressure",
            "output_images": True,
        }, "solid")
        if "error" in result:
            return False, result["error"]
        gif_file = result.get("data", {}).get("gif_file")
        if not gif_file or not os.path.exists(gif_file):
            return False, f"GIF not generated: {gif_file}"
        n_imgs = len(result.get("data", {}).get("image_files", []))
        return True, f"GIF: {os.path.basename(gif_file)}, {n_imgs} frames"

    def test_probe_line(self):
        self.engine.load_file("test_probe", FILE_YSY)
        # Use auto bbox for endpoints
        result = self.engine.calculate("test_probe", "probe_line", {
            "scalar": "Pressure",
            "resolution": 100,
        }, "solid")
        if "error" in result:
            return False, result["error"]
        csv_file = result.get("data", {}).get("csv_file")
        chart_file = result.get("data", {}).get("chart_file")
        if not csv_file or not os.path.exists(csv_file):
            return False, f"CSV missing: {csv_file}"
        if chart_file and not os.path.exists(chart_file):
            return False, f"Chart missing: {chart_file}"
        n_pts = result.get("data", {}).get("n_points", 0)
        return True, f"{n_pts} probed points, CSV+PNG"

    def test_render(self):
        self.engine.load_file("test_render", FILE_YSY)
        result = self.engine.calculate("test_render", "render",
                                       {"scalar": "Pressure"}, "solid")
        if "error" in result:
            return False, result["error"]
        out = result.get("data", {}).get("output_file")
        if not out or not os.path.exists(out):
            return False, f"PNG missing: {out}"
        return True, f"PNG: {os.path.basename(out)}"

    def test_compare_same_file(self):
        self.engine.load_file("test_cmp", FILE_YSY)
        result = self.engine.compare("test_cmp", "solid:Pressure", "solid:Pressure")
        if "error" in result:
            return False, result["error"]
        return True, "Same-zone compare works"

    def test_compare_cross_file(self):
        # Load x37b twice as different sessions to verify cross-file path
        # (Real cross-file would need consistent scalar naming across files)
        self.engine.load_file("test_xcmp", FILE_X37B)
        # Use same file for both sides to test the cross-file API path
        result = self.engine.compare("test_xcmp",
                                     "Elem_Tetras:pressure",
                                     "Elem_Tetras:pressure",
                                     file_b=FILE_X37B)
        if "error" in result:
            return False, result["error"]
        return True, "Cross-file API path works"

    def test_streamline(self):
        self.engine.load_file("test_sl", FILE_YSY)
        result = self.engine.calculate("test_sl", "streamline", {
            "n_seeds": 20, "seed_strategy": "auto",
        }, "solid")
        if "error" in result:
            return False, result["error"]
        out = result.get("output_files", [None])[0]
        return True, f"Streamlines saved: {os.path.basename(out) if out else '?'}"

    # --- Run all ---
    def run(self, quick=False):
        print(_c("=" * 70, "cyan"))
        print(_c("ChatCFD Backend Integration Test", "cyan"))
        print(_c("=" * 70, "cyan"))

        critical_tests = [
            ("Load ysy.cgns", self.test_load_ysy),
            ("Load x37b-02.cgns", self.test_load_x37b),
            ("Recursive search 'x37b'", self.test_recursive_search),
            ("Statistics on solid zone", self.test_statistics),
            ("Quality check", self.test_check),
            ("Slice + GIF (one-step)", self.test_slice_with_gif),
            ("Probe line + auto chart", self.test_probe_line),
        ]

        extra_tests = [
            ("Slice basic (no images)", self.test_slice_basic),
            ("Render zone PNG", self.test_render),
            ("Compare same-file", self.test_compare_same_file),
            ("Compare cross-file", self.test_compare_cross_file),
            ("Streamline (vtk engine)", self.test_streamline),
        ]

        for name, func in critical_tests:
            self._run(name, func, critical=True)
        if not quick:
            for name, func in extra_tests:
                self._run(name, func)

        # Summary
        print()
        print(_c("=" * 70, "cyan"))
        print(_c("SUMMARY", "cyan"))
        print(_c("=" * 70, "cyan"))
        passed = sum(1 for _, ok, _, _, _ in self.results if ok)
        failed = len(self.results) - passed
        total_time = sum(t for _, _, t, _, _ in self.results)
        print(f"Total: {len(self.results)}   {_c(f'Passed: {passed}', 'green')}   "
              f"{_c(f'Failed: {failed}', 'red' if failed else 'green')}   Time: {total_time:.1f}s")

        if failed:
            print(f"\n{_c('Failed tests:', 'red')}")
            for name, ok, elapsed, msg, critical in self.results:
                if not ok:
                    marker = " *" if critical else ""
                    print(f"  X {name}{marker}: {msg}")

        return failed == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="Only critical tests")
    args = parser.parse_args()

    runner = TestRunner()
    success = runner.run(quick=args.quick)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
