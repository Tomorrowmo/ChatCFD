import numpy as np
import pytest
from unittest.mock import MagicMock

from post_service.algorithms.compare import NAME, DESCRIPTION, DEFAULTS, execute


def _make_mock_post_data(zone_scalars: dict):
    """Create a mock PostData. zone_scalars: {(zone, scalar): np.ndarray}."""
    mock = MagicMock()

    def _get_scalar(zone, name):
        key = (zone, name)
        if key in zone_scalars:
            return zone_scalars[key]
        raise ValueError(f"Scalar '{name}' not found in zone '{zone}'.")

    mock.get_scalar.side_effect = _get_scalar
    return mock


class TestCompareMetadata:
    def test_name(self):
        assert NAME == "compare"

    def test_defaults_structure(self):
        assert isinstance(DEFAULTS, dict)
        assert "scalar" in DEFAULTS
        assert "zone_a" in DEFAULTS
        assert "zone_b" in DEFAULTS


class TestCompareExecute:
    def test_basic_comparison(self):
        arr_a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        arr_b = np.array([2.0, 3.0, 4.0, 5.0, 6.0])
        mock_pd = _make_mock_post_data({
            ("wall", "Pressure"): arr_a,
            ("inlet", "Pressure"): arr_b,
        })
        result = execute(mock_pd, {"scalar": "Pressure", "zone_a": "wall", "zone_b": "inlet"}, "")

        assert result["type"] == "comparison"
        assert "summary" in result
        assert result["output_files"] == []

        data = result["data"]
        assert data["scalar"] == "Pressure"
        assert data["zone_a"]["zone"] == "wall"
        assert data["zone_b"]["zone"] == "inlet"

        # wall mean=3.0, inlet mean=4.0
        assert data["zone_a"]["mean"] == pytest.approx(3.0)
        assert data["zone_b"]["mean"] == pytest.approx(4.0)
        assert data["diff"]["mean_diff"] == pytest.approx(-1.0)

    def test_identical_zones(self):
        arr = np.array([10.0, 20.0, 30.0])
        mock_pd = _make_mock_post_data({
            ("wall", "T"): arr,
            ("far", "T"): arr,
        })
        result = execute(mock_pd, {"scalar": "T", "zone_a": "wall", "zone_b": "far"}, "")

        assert result["data"]["diff"]["mean_diff"] == pytest.approx(0.0)
        assert result["data"]["diff"]["max_diff"] == pytest.approx(0.0)
        assert result["data"]["diff"]["min_diff"] == pytest.approx(0.0)

    def test_missing_scalar_param(self):
        mock_pd = MagicMock()
        result = execute(mock_pd, {"scalar": None, "zone_a": "a", "zone_b": "b"}, "")
        assert "error" in result

    def test_missing_zone_params(self):
        mock_pd = MagicMock()
        result = execute(mock_pd, {"scalar": "P", "zone_a": None, "zone_b": None}, "")
        assert "error" in result

    def test_bad_zone_returns_error(self):
        mock_pd = _make_mock_post_data({})
        result = execute(mock_pd, {"scalar": "P", "zone_a": "bad", "zone_b": "worse"}, "")
        assert "error" in result

    def test_stats_values(self):
        arr_a = np.array([0.0, 10.0])
        arr_b = np.array([5.0, 5.0])
        mock_pd = _make_mock_post_data({
            ("z1", "S"): arr_a,
            ("z2", "S"): arr_b,
        })
        result = execute(mock_pd, {"scalar": "S", "zone_a": "z1", "zone_b": "z2"}, "")
        data = result["data"]

        assert data["zone_a"]["min"] == pytest.approx(0.0)
        assert data["zone_a"]["max"] == pytest.approx(10.0)
        assert data["zone_a"]["mean"] == pytest.approx(5.0)
        assert data["zone_a"]["std"] == pytest.approx(5.0)
        assert data["zone_a"]["count"] == 2

        assert data["zone_b"]["mean"] == pytest.approx(5.0)
        assert data["zone_b"]["std"] == pytest.approx(0.0)

        assert data["diff"]["mean_diff"] == pytest.approx(0.0)
        assert data["diff"]["mean_diff_percent"] == pytest.approx(0.0)

    def test_mean_diff_percent_with_zero_means(self):
        """When both means are zero, mean_diff_percent should be 0."""
        arr = np.array([-1.0, 1.0])
        mock_pd = _make_mock_post_data({
            ("a", "X"): arr,
            ("b", "X"): arr,
        })
        result = execute(mock_pd, {"scalar": "X", "zone_a": "a", "zone_b": "b"}, "")
        assert result["data"]["diff"]["mean_diff_percent"] == pytest.approx(0.0)
