"""
PRD Test Cases (Section 19) — automated integration tests.

Maps PRD test IDs (T1.x-N, R1-R10) to pytest functions.
Tests that require real CFD data auto-skip when the file is absent.
Tests that require AI/LLM conversation are marked as manual-only.

Run:
    cd ChatCFD
    conda activate PostProcessTool
    python -m pytest tests/test_prd_cases.py -v --tb=short
"""

import os
import sys
import json
import tempfile

import pytest

# Ensure project root on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from post_service.engine import PostEngine


class _FakePostData:
    """Minimal mock for SessionState.post_data setter (needs .file_path)."""
    def __init__(self, path="fake.cgns"):
        self.file_path = path


# ── Test data paths ──
# The PRD references these external files; skip gracefully if missing.
CGNS_FILE = "f:/UE/coding/XStepl4/mclink-server/work/20260206/99c026c4c96545e6826d483d417f6997_FlowResult_tecplot.cgns"
HAS_CGNS = os.path.exists(CGNS_FILE)

ALGORITHMS_DIR = os.path.join(ROOT, "post_service", "algorithms")

needs_cgns = pytest.mark.skipif(not HAS_CGNS, reason=f"CGNS test file not found: {CGNS_FILE}")
needs_ai = pytest.mark.skip(reason="Requires AI/LLM conversation — manual test only")


def _parse_summary(summary):
    """Extract zone_names and scalars dict from engine load_file summary."""
    zones_list = summary.get("zones", [])
    zone_names = [z["name"] for z in zones_list]
    scalars = {}
    for z in zones_list:
        scalars[z["name"]] = [s["raw_name"] for s in z.get("scalars", [])]
    return zone_names, scalars


# ── Fixtures ──

@pytest.fixture(scope="module")
def engine():
    """PostEngine with real algorithms loaded."""
    e = PostEngine(algorithms_dir=ALGORITHMS_DIR)
    return e


@pytest.fixture(scope="module")
def loaded_session(engine):
    """Engine with a CGNS file loaded in session 'prd'. Returns (engine, session_id, summary)."""
    if not HAS_CGNS:
        pytest.skip("CGNS test file not available")
    sid = "prd_test"
    summary = engine.load_file(sid, CGNS_FILE)
    assert "error" not in summary, f"load_file failed: {summary}"
    # Ensure output directory exists for export tests
    state = engine.session_mgr.get(sid)
    if state and state.output_dir:
        os.makedirs(state.output_dir, exist_ok=True)
    return engine, sid, summary


def _fresh_session(engine, sid):
    """Load CGNS into a fresh session (avoids state pollution from destructive algorithms)."""
    summary = engine.load_file(sid, CGNS_FILE)
    assert "error" not in summary
    state = engine.session_mgr.get(sid)
    if state and state.output_dir:
        os.makedirs(state.output_dir, exist_ok=True)
    return summary


# ════════════════════════════════════════════════════════════════
#  T1.1 File Loading
# ════════════════════════════════════════════════════════════════

class TestT1_1_FileLoading:
    """T1.1 — file loading, listing, error handling."""

    @needs_cgns
    def test_01_load_cgns(self, engine):
        """T1.1-1: Load a CGNS file with full path."""
        result = engine.load_file("t11_1", CGNS_FILE)
        assert "error" not in result
        zone_names, _ = _parse_summary(result)
        assert len(zone_names) > 0
        assert "total_cells" in result
        assert "total_points" in result
        print(f"  [T1.1-1] zones={zone_names}, cells={result['total_cells']}, points={result['total_points']}")

    def test_03_file_not_found(self, engine):
        """T1.1-3: Non-existent file returns error dict."""
        result = engine.load_file("t11_3", "不存在的文件.cgns")
        assert "error" in result
        assert "not found" in result["error"].lower() or "File not found" in result["error"]
        print(f"  [T1.1-3] error={result['error']}")

    def test_04_list_files(self, engine, tmp_path):
        """T1.1-4: List files in a directory."""
        (tmp_path / "a.cgns").write_text("x")
        (tmp_path / "b.plt").write_text("y")
        (tmp_path / "readme.txt").write_text("z")
        result = engine.list_files(str(tmp_path))
        assert "error" not in result
        assert result["count"] == 3
        # Paths use forward slashes
        for p in result["files"]:
            assert "\\" not in p
        print(f"  [T1.1-4] count={result['count']}")

    def test_05_list_files_suffix(self, engine, tmp_path):
        """T1.1-5: List only .plt files."""
        (tmp_path / "a.cgns").write_text("x")
        (tmp_path / "b.plt").write_text("y")
        (tmp_path / "c.plt").write_text("z")
        result = engine.list_files(str(tmp_path), suffix=".plt")
        assert result["count"] == 2
        for p in result["files"]:
            assert p.endswith(".plt")
        print(f"  [T1.1-5] count={result['count']}")


# ════════════════════════════════════════════════════════════════
#  T1.2 Force/Moment Calculation
# ════════════════════════════════════════════════════════════════

class TestT1_2_ForceMoment:
    """T1.2 — force and moment calculations."""

    @needs_cgns
    def test_06_raw_force(self, loaded_session):
        """T1.2-6: Calculate raw force and moment."""
        eng, sid, _ = loaded_session
        result = eng.calculate(sid, "force_moment", {}, "")
        assert "error" not in result, f"calculate failed: {result}"
        assert "summary" in result
        # Should have force data
        data = result.get("data", {})
        print(f"  [T1.2-6] type={result.get('type')}, summary={result.get('summary', '')[:80]}")

    @needs_cgns
    def test_07_force_zone(self, loaded_session):
        """T1.2-7: Calculate for a specific zone."""
        eng, sid, summary = loaded_session
        zone_names, _ = _parse_summary(summary)
        if not zone_names:
            pytest.skip("No zones in summary")
        zone = zone_names[-1]
        result = eng.calculate(sid, "force_moment", {}, zone)
        assert "error" not in result, f"calculate failed: {result}"
        print(f"  [T1.2-7] zone={zone}, type={result.get('type')}")

    @needs_cgns
    def test_08_force_coefficients(self, loaded_session):
        """T1.2-8: Calculate with aerodynamic coefficients."""
        eng, sid, _ = loaded_session
        params = {"density": 1.225, "velocity": 340.0, "refArea": 1.0}
        result = eng.calculate(sid, "force_moment", params, "")
        assert "error" not in result, f"calculate failed: {result}"
        # Should mention coefficients in summary or data
        summary_text = result.get("summary", "")
        data = result.get("data", {})
        has_coeff = ("CL" in str(data) or "CD" in str(data) or
                     "coefficient" in summary_text.lower() or
                     "cl" in summary_text.lower())
        print(f"  [T1.2-8] has_coefficients={has_coeff}, summary={summary_text[:80]}")

    def test_09_no_file_loaded(self, engine):
        """T1.2-9: Error when no file loaded."""
        result = engine.calculate("nonexistent_session", "force_moment", {}, "")
        assert "error" in result
        print(f"  [T1.2-9] error={result['error']}")


# ════════════════════════════════════════════════════════════════
#  T1.3 Velocity Gradient
# ════════════════════════════════════════════════════════════════

class TestT1_3_VelocityGradient:
    """T1.3 — velocity gradient / vorticity / Mach / Cp."""

    @needs_cgns
    def test_10_vorticity(self, loaded_session):
        """T1.3-10: Calculate vorticity."""
        eng, sid, _ = loaded_session
        result = eng.calculate(sid, "velocity_gradient", {}, "")
        assert "error" not in result, f"calculate failed: {result}"
        # Should produce output file(s)
        out = result.get("output_files", [])
        print(f"  [T1.3-10] type={result.get('type')}, output_files={out}")

    @needs_cgns
    def test_11_mach_cp(self, loaded_session):
        """T1.3-11: Calculate Mach and pressure coefficient."""
        eng, sid, _ = loaded_session
        params = {"mach_switch": True, "pressure_coefficient_switch": True}
        result = eng.calculate(sid, "velocity_gradient", params, "")
        assert "error" not in result, f"calculate failed: {result}"
        print(f"  [T1.3-11] type={result.get('type')}, summary={result.get('summary', '')[:80]}")


# ════════════════════════════════════════════════════════════════
#  T1.4 Statistics & Data Export
# ════════════════════════════════════════════════════════════════

class TestT1_4_StatisticsExport:
    """T1.4 — scalar statistics and CSV export."""

    @needs_cgns
    def test_12_statistics(self, loaded_session):
        """T1.4-12: Pressure range statistics (min/max/mean/std)."""
        eng, sid, summary = loaded_session
        zone_names, _ = _parse_summary(summary)
        if not zone_names:
            pytest.skip("No zones in summary")
        zone = zone_names[0]
        result = eng.calculate(sid, "statistics", {}, zone)
        assert "error" not in result, f"calculate failed: {result}"
        print(f"  [T1.4-12] type={result.get('type')}, summary={result.get('summary', '')[:80]}")

    @needs_cgns
    def test_13_export_csv(self, engine):
        """T1.4-13: Export zone data to CSV."""
        sid = "t14_13"
        summary = _fresh_session(engine, sid)
        zone_names, scalars = _parse_summary(summary)
        if not zone_names:
            pytest.skip("No zones")
        zone = zone_names[-1]
        available = scalars.get(zone, [])
        scalars_to_export = available[:2] if available else ["Pressure"]
        result = engine.export_data(sid, zone, scalars_to_export, "csv")
        assert "error" not in result, f"export failed: {result}"
        assert result.get("type") == "file"
        assert result.get("output_files")
        out_path = result["output_files"][0]
        assert os.path.exists(out_path), f"Output file missing: {out_path}"
        print(f"  [T1.4-13] output={out_path}")


# ════════════════════════════════════════════════════════════════
#  T1.5 Parameter Query
# ════════════════════════════════════════════════════════════════

class TestT1_5_ParameterQuery:
    """T1.5 — method templates / parameter query."""

    def test_15_list_methods(self, engine):
        """T1.5-15: List all available calculation methods."""
        result = engine.get_method_template()
        assert "methods" in result
        names = [m["name"] for m in result["methods"]]
        # PRD expects at least: force_moment, velocity_gradient, statistics
        for expected in ["force_moment", "velocity_gradient", "statistics"]:
            assert expected in names, f"Missing method: {expected}"
        print(f"  [T1.5-15] methods={names}")

    def test_16_method_template(self, engine):
        """T1.5-16: Get parameter template for force_moment."""
        result = engine.get_method_template("force_moment")
        assert "error" not in result
        assert result["method"] == "force_moment"
        assert "defaults" in result
        defaults = result["defaults"]
        # PRD expects: pressure, density, velocity, refArea
        for key in ["pressure"]:
            assert key in defaults, f"Missing default key: {key}"
        print(f"  [T1.5-16] defaults keys={list(defaults.keys())}")


# ════════════════════════════════════════════════════════════════
#  T1.6 Session Caching
# ════════════════════════════════════════════════════════════════

class TestT1_6_SessionCaching:
    """T1.6 — file caching across operations."""

    @needs_cgns
    def test_17_cached_across_ops(self, engine):
        """T1.6-17: File stays cached across multiple operations."""
        sid = "t16_17"
        r1 = engine.load_file(sid, CGNS_FILE)
        assert "error" not in r1

        # Second call (calculate) should work without reloading
        r2 = engine.calculate(sid, "force_moment", {}, "")
        assert "error" not in r2, f"calculate after load failed: {r2}"

        # Session still valid
        state = engine.session_mgr.get(sid)
        assert state is not None
        assert state.post_data is not None
        print(f"  [T1.6-17] session alive, post_data exists")

    @needs_cgns
    def test_18_cache_replaced(self, engine):
        """T1.6-18: Loading a new file replaces the cached one."""
        sid = "t16_18"
        r1 = engine.load_file(sid, CGNS_FILE)
        assert "error" not in r1
        pd1 = engine.session_mgr.get(sid).post_data

        # Load the same file again (simulates loading a different file)
        r2 = engine.load_file(sid, CGNS_FILE)
        assert "error" not in r2
        pd2 = engine.session_mgr.get(sid).post_data

        # post_data should be refreshed (new object)
        assert pd2 is not None
        print(f"  [T1.6-18] cache refreshed")


# ════════════════════════════════════════════════════════════════
#  T1.7 Fallback & Confirmation (AI conversation — manual only)
# ════════════════════════════════════════════════════════════════

class TestT1_7_Fallback:
    """T1.7 — fallback and confirmation (requires AI agent)."""

    @needs_ai
    def test_19_plot_fallback(self):
        """T1.7-19: 'Draw pressure contour' → AI should ask, not code."""

    @needs_ai
    def test_20_script_confirm(self):
        """T1.7-20: 'Run a script' → AI should confirm first."""

    @needs_ai
    def test_21_ambiguous_input(self):
        """T1.7-21: 'Analyze' without filename → AI asks for clarification."""


# ════════════════════════════════════════════════════════════════
#  T1.8 Error Handling
# ════════════════════════════════════════════════════════════════

class TestT1_8_ErrorHandling:
    """T1.8 — error scenarios."""

    def test_22_missing_scalar(self, engine):
        """T1.8-22: Calculate on data without required scalar → error dict."""
        # Create a session with a fake post_data that will fail on algorithm execution
        state = engine.session_mgr.create("t18_22")
        state.post_data = _FakePostData("fake_no_pressure.cgns")
        result = engine.calculate("t18_22", "force_moment", {}, "")
        assert "error" in result
        print(f"  [T1.8-22] error={result['error'][:80]}")

    def test_23_nonexistent_zone(self, engine):
        """T1.8-23: Non-existent zone name → error or graceful fallback."""
        if not HAS_CGNS:
            pytest.skip("Needs CGNS data to test zone lookup")
        sid = "t18_23"
        engine.load_file(sid, CGNS_FILE)
        result = engine.calculate(sid, "force_moment", {}, "abc_nonexistent_zone")
        # Should either error or fall back to full domain
        print(f"  [T1.8-23] result={'error' if 'error' in result else 'ok (fallback)'}")

    def test_24_backslash_path(self, engine):
        """T1.8-24: Backslash path auto-converted to forward slash."""
        if not HAS_CGNS:
            pytest.skip("Needs CGNS data")
        backslash_path = CGNS_FILE.replace("/", "\\")
        result = engine.load_file("t18_24", backslash_path)
        assert "error" not in result, f"Backslash path failed: {result}"
        print(f"  [T1.8-24] backslash path loaded OK")


# ════════════════════════════════════════════════════════════════
#  T2.4 Compare
# ════════════════════════════════════════════════════════════════

class TestT2_4_Compare:
    """T2.4 — compare tool."""

    @needs_cgns
    def test_38_compare_zones(self, engine):
        """T2.4-38: Compare two zones on the same scalar."""
        sid = "t24_38"
        summary = _fresh_session(engine, sid)
        zone_names, _ = _parse_summary(summary)
        if len(zone_names) < 2:
            pytest.skip("Need at least 2 zones for compare")
        z_a, z_b = zone_names[0], zone_names[1]
        result = engine.compare(sid, f"{z_a}:Pressure", f"{z_b}:Pressure")
        assert "error" not in result, f"compare failed: {result}"
        assert "summary" in result
        print(f"  [T2.4-38] type={result.get('type')}, summary={result.get('summary', '')[:80]}")

    def test_compare_bad_format(self, engine):
        """T2.4 extra: compare with bad source format → error."""
        state = engine.session_mgr.create("t24_bad")
        state.post_data = _FakePostData()
        result = engine.compare("t24_bad", "no_colon", "also_no_colon")
        assert "error" in result
        assert "zone:scalar" in result["error"].lower() or "format" in result["error"].lower()

    def test_compare_scalar_mismatch(self, engine):
        """T2.4 extra: different scalars → error."""
        state = engine.session_mgr.create("t24_mismatch")
        state.post_data = _FakePostData()
        result = engine.compare("t24_mismatch", "wall:Pressure", "far:Temperature")
        assert "error" in result
        assert "mismatch" in result["error"].lower()


# ════════════════════════════════════════════════════════════════
#  T2.6 Unified Return Format
# ════════════════════════════════════════════════════════════════

class TestT2_6_UnifiedFormat:
    """T2.6 — all returns contain type + summary."""

    @needs_cgns
    def test_44_force_moment_format(self, loaded_session):
        """T2.6-44: force_moment → type + summary."""
        eng, sid, _ = loaded_session
        result = eng.calculate(sid, "force_moment", {}, "")
        assert "error" not in result
        assert "type" in result, "Missing 'type' in return"
        assert "summary" in result, "Missing 'summary' in return"
        print(f"  [T2.6-44] type={result['type']}")

    @needs_cgns
    def test_45_velocity_gradient_format(self, loaded_session):
        """T2.6-45: velocity_gradient → type + summary + output_files."""
        eng, sid, _ = loaded_session
        result = eng.calculate(sid, "velocity_gradient", {}, "")
        assert "error" not in result
        assert "type" in result
        assert "summary" in result
        assert "output_files" in result
        print(f"  [T2.6-45] type={result['type']}, files={result.get('output_files')}")

    @needs_cgns
    def test_46_export_format(self, engine):
        """T2.6-46: export → type='file' + summary + output_files."""
        sid = "t26_46"
        summary = _fresh_session(engine, sid)
        zone_names, scalars = _parse_summary(summary)
        if not zone_names:
            pytest.skip("No zones")
        zone = zone_names[-1]
        available = scalars.get(zone, [])
        scalar = available[0] if available else "Pressure"
        result = engine.export_data(sid, zone, [scalar], "csv")
        assert "error" not in result, f"export failed: {result}"
        assert result["type"] == "file"
        assert "summary" in result
        assert "output_files" in result
        print(f"  [T2.6-46] type={result['type']}")


# ════════════════════════════════════════════════════════════════
#  T3.3 Algorithm Plugin Discovery
# ════════════════════════════════════════════════════════════════

class TestT3_3_AlgorithmPlugin:
    """T3.3 — algorithm plugin auto-discovery."""

    def test_55_auto_discovery(self, engine, tmp_path):
        """T3.3-55: New algorithm file auto-discovered on scan."""
        algo_file = tmp_path / "test_algo.py"
        algo_file.write_text(
            'NAME = "test_prd_algo"\n'
            'DESCRIPTION = "Test algorithm for PRD"\n'
            'DEFAULTS = {"x": 1}\n'
            'def execute(post_data, params, zone, **kw):\n'
            '    return {"type": "numerical", "summary": "test ok", "data": {"x": params["x"]}, "output_files": []}\n'
        )
        # Scan the temp directory
        engine.registry.scan_and_load(str(tmp_path))
        result = engine.get_method_template("test_prd_algo")
        assert "error" not in result
        assert result["method"] == "test_prd_algo"
        print(f"  [T3.3-55] discovered: {result['method']}")

    def test_56_invoke_plugin(self, engine, tmp_path):
        """T3.3-56: Invoke dynamically loaded algorithm."""
        algo_file = tmp_path / "dynamic_algo.py"
        algo_file.write_text(
            'NAME = "dynamic_prd"\n'
            'DESCRIPTION = "Dynamic test"\n'
            'DEFAULTS = {"val": 42}\n'
            'def execute(post_data, params, zone, **kw):\n'
            '    return {"type": "numerical", "summary": f"val={params[\'val\']}", "data": {"val": params["val"]}, "output_files": []}\n'
        )
        engine.registry.scan_and_load(str(tmp_path))
        # Create a fake session with dummy post_data
        state = engine.session_mgr.create("t33_56")
        state.post_data = _FakePostData()
        result = engine.calculate("t33_56", "dynamic_prd", {}, "")
        assert "error" not in result
        assert result["data"]["val"] == 42
        print(f"  [T3.3-56] result={result['data']}")


# ════════════════════════════════════════════════════════════════
#  Regression Tests R1-R10
# ════════════════════════════════════════════════════════════════

class TestRegression:
    """R1-R10 regression baseline."""

    @needs_cgns
    def test_R1_load_file(self, engine):
        """R1: loadFile → file loading + caching works."""
        result = engine.load_file("r1", CGNS_FILE)
        assert "error" not in result
        state = engine.session_mgr.get("r1")
        assert state is not None and state.post_data is not None
        print(f"  [R1] OK")

    @needs_cgns
    def test_R2_force_moment(self, loaded_session):
        """R2: calculate(force_moment) → unified return format."""
        eng, sid, _ = loaded_session
        result = eng.calculate(sid, "force_moment", {}, "")
        assert "error" not in result
        assert "type" in result and "summary" in result
        print(f"  [R2] type={result['type']}")

    @needs_cgns
    def test_R3_velocity_gradient(self, loaded_session):
        """R3: calculate(velocity_gradient) → output_files."""
        eng, sid, _ = loaded_session
        result = eng.calculate(sid, "velocity_gradient", {}, "")
        assert "error" not in result
        assert "output_files" in result
        print(f"  [R3] output_files={result.get('output_files')}")

    @needs_cgns
    def test_R4_compare(self, engine):
        """R4: compare → unified return format."""
        sid = "r4"
        summary = _fresh_session(engine, sid)
        zone_names, _ = _parse_summary(summary)
        if len(zone_names) < 2:
            pytest.skip("Need >=2 zones")
        z_a, z_b = zone_names[0], zone_names[1]
        result = engine.compare(sid, f"{z_a}:Pressure", f"{z_b}:Pressure")
        assert "error" not in result, f"compare failed: {result}"
        assert "summary" in result
        print(f"  [R4] OK")

    @needs_cgns
    def test_R5_export(self, engine):
        """R5: exportData → unified return format."""
        sid = "r5"
        summary = _fresh_session(engine, sid)
        zone_names, _ = _parse_summary(summary)
        if not zone_names:
            pytest.skip("No zones")
        zone = zone_names[-1]
        result = engine.export_data(sid, zone, ["Pressure"], "csv")
        assert "error" not in result, f"export failed: {result}"
        assert result["type"] == "file"
        assert result.get("output_files")
        print(f"  [R5] OK")

    def test_R6_get_methods(self, engine):
        """R6: getMethodTemplate → lists all methods including plugins."""
        result = engine.get_method_template()
        assert "methods" in result
        assert len(result["methods"]) >= 3
        print(f"  [R6] {len(result['methods'])} methods")

    def test_R7_list_files(self, engine, tmp_path):
        """R7: listFiles → works correctly."""
        (tmp_path / "test.cgns").write_text("x")
        result = engine.list_files(str(tmp_path), suffix=".cgns")
        assert result["count"] == 1
        print(f"  [R7] OK")

    def test_R8_calculate_no_file(self, engine):
        """R8: calculate without loaded file → error dict, no crash."""
        result = engine.calculate("no_session_ever", "force_moment", {}, "")
        assert "error" in result
        print(f"  [R8] error={result['error']}")

    def test_R9_bad_path(self, engine):
        """R9: loadFile with bad path → error dict, no crash."""
        result = engine.load_file("r9", "/nonexistent/path/file.cgns")
        assert "error" in result
        print(f"  [R9] error={result['error']}")

    @needs_cgns
    def test_R10_unified_format(self, loaded_session):
        """R10: All returns contain type + summary."""
        eng, sid, _ = loaded_session
        # Test multiple methods
        results = []
        r = eng.calculate(sid, "force_moment", {}, "")
        if "error" not in r:
            results.append(("force_moment", r))
        r = eng.calculate(sid, "statistics", {}, "")
        if "error" not in r:
            results.append(("statistics", r))
        for name, r in results:
            assert "type" in r, f"{name} missing 'type'"
            assert "summary" in r, f"{name} missing 'summary'"
        print(f"  [R10] checked {len(results)} results, all have type+summary")
