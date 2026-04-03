"""Tests for PostEngine — mock-based for VTK-dependent paths, real for pure logic."""

import os
import tempfile

import pytest

from post_service.engine import PostEngine


@pytest.fixture
def engine(tmp_path):
    """PostEngine with a tiny fake algorithm registered."""
    e = PostEngine()
    # Manually register a fake algorithm for testing
    e.registry.methods["fake_stats"] = {
        "name": "fake_stats",
        "description": "A fake algorithm for testing",
        "defaults": {"scalar": "pressure"},
        "execute": lambda pd, params, zone: {
            "type": "table",
            "summary": f"Computed fake_stats on {zone}",
            "data": {"mean": 1.0},
        },
    }
    return e


# ------------------------------------------------------------------
# list_files
# ------------------------------------------------------------------

class TestListFiles:
    def test_list_files(self, tmp_path):
        # Create some files
        (tmp_path / "a.cgns").write_text("x")
        (tmp_path / "b.txt").write_text("y")
        (tmp_path / "c.cgns").write_text("z")
        engine = PostEngine()
        result = engine.list_files(str(tmp_path))
        assert "error" not in result
        assert result["count"] == 3
        # Paths should be forward-slash normalized
        for p in result["files"]:
            assert "\\" not in p

    def test_list_files_with_suffix(self, tmp_path):
        (tmp_path / "a.cgns").write_text("x")
        (tmp_path / "b.txt").write_text("y")
        (tmp_path / "c.cgns").write_text("z")
        engine = PostEngine()
        result = engine.list_files(str(tmp_path), suffix=".cgns")
        assert result["count"] == 2
        for p in result["files"]:
            assert p.endswith(".cgns")

    def test_list_files_bad_dir(self):
        engine = PostEngine()
        result = engine.list_files("/no/such/directory/ever")
        assert "error" in result


# ------------------------------------------------------------------
# get_method_template
# ------------------------------------------------------------------

class TestGetMethodTemplate:
    def test_all(self, engine):
        result = engine.get_method_template()
        assert "methods" in result
        names = [m["name"] for m in result["methods"]]
        assert "fake_stats" in names

    def test_specific(self, engine):
        result = engine.get_method_template("fake_stats")
        assert result["method"] == "fake_stats"
        assert "defaults" in result

    def test_unknown(self, engine):
        result = engine.get_method_template("nonexistent_method")
        assert "error" in result


# ------------------------------------------------------------------
# calculate — error paths (no VTK needed)
# ------------------------------------------------------------------

class TestCalculateErrors:
    def test_no_session(self, engine):
        result = engine.calculate("no_session", "fake_stats", {}, "")
        assert "error" in result
        assert "Session not found" in result["error"]

    def test_no_file(self, engine):
        engine.session_mgr.create("s1")
        result = engine.calculate("s1", "fake_stats", {}, "")
        assert "error" in result
        assert "No file loaded" in result["error"]

    def test_unknown_method(self, engine):
        state = engine.session_mgr.create("s2")
        state.post_data = object()  # fake non-None post_data
        result = engine.calculate("s2", "no_such_method", {}, "")
        assert "error" in result
        assert "Unknown method" in result["error"]


# ------------------------------------------------------------------
# load_file — file-not-found (no VTK needed)
# ------------------------------------------------------------------

class TestLoadFileErrors:
    def test_file_not_found(self):
        engine = PostEngine()
        result = engine.load_file("s1", "/no/such/file.cgns")
        assert "error" in result
        assert "File not found" in result["error"]


# ------------------------------------------------------------------
# export_data / compare — error paths
# ------------------------------------------------------------------

class TestExportCompareErrors:
    def test_export_no_file(self):
        engine = PostEngine()
        result = engine.export_data("s1", "zone", ["p"], "csv")
        assert "error" in result

    def test_compare_no_file(self):
        engine = PostEngine()
        result = engine.compare("s1", "a", "b")
        assert "error" in result
