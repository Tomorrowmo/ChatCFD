import numpy as np
import pytest
from unittest.mock import MagicMock

from post_service.algorithms.statistics import NAME, DESCRIPTION, DEFAULTS, execute


def _make_mock_post_data(scalar_map: dict, scalar_names: list | None = None):
    """Create a mock PostData with given scalar arrays per zone."""
    mock = MagicMock()

    def _get_scalar(zone, name):
        if name in scalar_map:
            return scalar_map[name]
        raise ValueError(f"Unknown scalar {name}")

    mock.get_scalar.side_effect = _get_scalar
    if scalar_names is not None:
        mock.get_scalar_names.return_value = scalar_names
    return mock


class TestStatisticsMetadata:
    def test_name(self):
        assert NAME == "statistics"

    def test_defaults_structure(self):
        assert isinstance(DEFAULTS, dict)
        assert "scalars" in DEFAULTS


class TestStatisticsExecute:
    def test_single_scalar(self):
        arr = np.array([1, 2, 3, 4, 5], dtype=float)
        mock_pd = _make_mock_post_data({"pressure": arr}, scalar_names=["pressure"])
        result = execute(mock_pd, {"scalars": ["pressure"]}, "wall")

        stats = result["data"]["pressure"]
        assert stats["min"] == pytest.approx(1.0)
        assert stats["max"] == pytest.approx(5.0)
        assert stats["mean"] == pytest.approx(3.0)
        assert stats["std"] == pytest.approx(np.std([1, 2, 3, 4, 5]))

    def test_all_scalars_when_none(self):
        arr_p = np.array([10, 20, 30], dtype=float)
        arr_t = np.array([100, 200, 300], dtype=float)
        mock_pd = _make_mock_post_data(
            {"pressure": arr_p, "temperature": arr_t},
            scalar_names=["pressure", "temperature"],
        )
        result = execute(mock_pd, {"scalars": None}, "inlet")

        mock_pd.get_scalar_names.assert_called_once_with("inlet")
        assert "pressure" in result["data"]
        assert "temperature" in result["data"]

    def test_return_format(self):
        arr = np.array([1, 2, 3], dtype=float)
        mock_pd = _make_mock_post_data({"v": arr}, scalar_names=["v"])
        result = execute(mock_pd, {"scalars": ["v"]}, "zone1")

        assert result["type"] == "numerical"
        assert isinstance(result["summary"], str)
        assert isinstance(result["data"], dict)
        assert result["output_files"] == []

    def test_empty_zone(self):
        mock_pd = _make_mock_post_data({}, scalar_names=[])
        result = execute(mock_pd, {"scalars": None}, "empty_zone")

        assert result["data"] == {}
        assert result["output_files"] == []
