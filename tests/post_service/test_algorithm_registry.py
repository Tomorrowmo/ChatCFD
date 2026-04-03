import os
from post_service.algorithm_registry import AlgorithmRegistry


def _write_algo(directory, filename, content):
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


DUMMY_ALGO = """\
NAME = "dummy"
DESCRIPTION = "A dummy algorithm for testing"
DEFAULTS = {"param1": 1.0, "param2": "abc"}

def execute(post_data, params):
    return {"summary": "ok"}
"""


def test_scan_loads_algorithms(tmp_path):
    _write_algo(tmp_path, "dummy_algo.py", DUMMY_ALGO)
    reg = AlgorithmRegistry()
    reg.scan_and_load(str(tmp_path))
    assert "dummy" in reg.methods
    entry = reg.methods["dummy"]
    assert entry["name"] == "dummy"
    assert entry["description"] == "A dummy algorithm for testing"
    assert entry["defaults"] == {"param1": 1.0, "param2": "abc"}
    assert callable(entry["execute"])


def test_get_method(tmp_path):
    _write_algo(tmp_path, "dummy_algo.py", DUMMY_ALGO)
    reg = AlgorithmRegistry()
    reg.scan_and_load(str(tmp_path))
    assert reg.get("dummy") is not None
    assert reg.get("dummy")["name"] == "dummy"
    assert reg.get("nonexistent") is None


def test_list_methods(tmp_path):
    _write_algo(tmp_path, "dummy_algo.py", DUMMY_ALGO)
    reg = AlgorithmRegistry()
    reg.scan_and_load(str(tmp_path))
    methods = reg.list_methods()
    assert len(methods) == 1
    m = methods[0]
    assert m["name"] == "dummy"
    assert m["description"] == "A dummy algorithm for testing"
    assert m["defaults"] == {"param1": 1.0, "param2": "abc"}
    assert "execute" not in m


def test_ignores_underscored_files(tmp_path):
    _write_algo(tmp_path, "_private.py", DUMMY_ALGO.replace('"dummy"', '"private"'))
    reg = AlgorithmRegistry()
    reg.scan_and_load(str(tmp_path))
    assert len(reg.methods) == 0


def test_empty_dir(tmp_path):
    reg = AlgorithmRegistry()
    reg.scan_and_load(str(tmp_path))
    assert reg.methods == {}
    assert reg.list_methods() == []
