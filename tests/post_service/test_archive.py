"""Tests for AnalysisArchive."""

import json
import os

import pytest

from post_service.archive import AnalysisArchive


@pytest.fixture
def sample_file(tmp_path):
    """Create a small dummy file to archive against."""
    p = tmp_path / "test_data.cgns"
    p.write_bytes(b"fake cgns content for testing")
    return str(p)


def test_archive_path_format(sample_file):
    ap = AnalysisArchive.archive_path(sample_file)
    assert ap.endswith(".chatcfd/test_data.cgns.archive.json")
    assert "\\" not in ap


def test_save_and_load_entry(sample_file):
    path = AnalysisArchive.save_entry(
        sample_file,
        method="force_moment",
        zone="wall",
        params={"pressure": "Pressure", "density": 1.225},
        result={"CL": 0.35, "CD": 0.012},
        note="first run",
    )
    assert os.path.exists(path)

    archive = AnalysisArchive.load(sample_file)
    assert archive is not None
    assert archive["file"] == "test_data.cgns"
    assert len(archive["entries"]) == 1

    entry = archive["entries"][0]
    assert entry["method"] == "force_moment"
    assert entry["zone"] == "wall"
    assert entry["params"]["density"] == 1.225
    assert entry["result"]["CL"] == 0.35
    assert entry["note"] == "first run"
    assert "timestamp" in entry


def test_multiple_entries(sample_file):
    for i in range(3):
        AnalysisArchive.save_entry(
            sample_file,
            method=f"method_{i}",
            zone="wall",
            params={"i": i},
            result={"val": i * 10},
        )
    archive = AnalysisArchive.load(sample_file)
    assert len(archive["entries"]) == 3
    assert archive["entries"][2]["method"] == "method_2"


def test_check_consistency_no_archive(sample_file):
    result = AnalysisArchive.check_consistency(sample_file)
    assert result["has_archive"] is False


def test_check_consistency_matches(sample_file):
    AnalysisArchive.save_entry(
        sample_file, "test", "z", {}, {"x": 1}
    )
    result = AnalysisArchive.check_consistency(sample_file)
    assert result["has_archive"] is True
    assert result["md5_matches"] is True
    assert result["entries_count"] == 1
    assert "历史存档可用" in result["message"]


def test_check_consistency_file_changed(sample_file):
    AnalysisArchive.save_entry(
        sample_file, "test", "z", {}, {"x": 1}
    )
    # Modify the original file so MD5 no longer matches
    with open(sample_file, "wb") as f:
        f.write(b"modified content that differs from original")

    result = AnalysisArchive.check_consistency(sample_file)
    assert result["has_archive"] is True
    assert result["md5_matches"] is False
    assert "文件已更新" in result["message"]


def test_load_nonexistent(tmp_path):
    fake = str(tmp_path / "no_such_file.cgns")
    assert AnalysisArchive.load(fake) is None


def test_save_entry_default_note(sample_file):
    AnalysisArchive.save_entry(sample_file, "m", "z", {}, {})
    archive = AnalysisArchive.load(sample_file)
    assert archive["entries"][0]["note"] == ""
