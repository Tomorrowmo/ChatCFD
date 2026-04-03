"""Tests for PostData thin wrapper."""

import numpy as np
import pytest
import vtk

from post_service.post_data import PostData


def make_test_multiblock() -> vtk.vtkMultiBlockDataSet:
    """Create a minimal vtkMultiBlockDataSet with 2 blocks for testing.

    Block 0 "wall": 4 points (quad), has Static_Pressure + X_Velocity (point data)
    Block 1 "far":  4 points (quad), has Static_Pressure only (point data)
    """
    mb = vtk.vtkMultiBlockDataSet()
    mb.SetNumberOfBlocks(2)

    for idx, (name, scalars) in enumerate([
        ("wall", {"Static_Pressure": [100.0, 200.0, 300.0, 400.0],
                  "X_Velocity": [1.0, 2.0, 3.0, 4.0]}),
        ("far", {"Static_Pressure": [50.0, 60.0, 70.0, 80.0]}),
    ]):
        grid = vtk.vtkUnstructuredGrid()

        # Points: simple quad
        points = vtk.vtkPoints()
        points.InsertNextPoint(0.0, 0.0, 0.0)
        points.InsertNextPoint(1.0, 0.0, 0.0)
        points.InsertNextPoint(1.0, 1.0, 0.0)
        points.InsertNextPoint(0.0, 1.0, 0.0)
        grid.SetPoints(points)

        # One quad cell
        quad = vtk.vtkQuad()
        for i in range(4):
            quad.GetPointIds().SetId(i, i)
        grid.InsertNextCell(quad.GetCellType(), quad.GetPointIds())

        # Scalar arrays (point data)
        for arr_name, values in scalars.items():
            arr = vtk.vtkDoubleArray()
            arr.SetName(arr_name)
            arr.SetNumberOfTuples(4)
            for i, v in enumerate(values):
                arr.SetValue(i, v)
            grid.GetPointData().AddArray(arr)

        mb.SetBlock(idx, grid)
        mb.GetMetaData(idx).Set(vtk.vtkCompositeDataSet.NAME(), name)

    return mb


@pytest.fixture
def post_data():
    """Create a PostData instance with test multiblock."""
    mb = make_test_multiblock()
    return PostData(mb, "C:\\data\\test.cgns")


# ------------------------------------------------------------------
# Zone tests
# ------------------------------------------------------------------

class TestGetZones:
    def test_returns_all_zones(self, post_data):
        zones = post_data.get_zones()
        assert zones == ["wall", "far"]

    def test_zone_count(self, post_data):
        assert len(post_data.get_zones()) == 2


# ------------------------------------------------------------------
# Scalar access tests
# ------------------------------------------------------------------

class TestGetScalar:
    def test_raw_name(self, post_data):
        arr = post_data.get_scalar("wall", "Static_Pressure")
        np.testing.assert_array_equal(arr, [100.0, 200.0, 300.0, 400.0])

    def test_standard_name_maps_to_raw(self, post_data):
        """'pressure' should resolve to 'Static_Pressure' via mapping."""
        arr = post_data.get_scalar("wall", "pressure")
        np.testing.assert_array_equal(arr, [100.0, 200.0, 300.0, 400.0])

    def test_standard_name_velocity_x(self, post_data):
        """'velocity_x' should resolve to 'X_Velocity'."""
        arr = post_data.get_scalar("wall", "velocity_x")
        np.testing.assert_array_equal(arr, [1.0, 2.0, 3.0, 4.0])

    def test_writeable_false(self, post_data):
        arr = post_data.get_scalar("wall", "Static_Pressure")
        assert arr.flags.writeable is False
        with pytest.raises(ValueError):
            arr[0] = 999.0

    def test_invalid_zone_raises(self, post_data):
        with pytest.raises(ValueError, match="Zone 'nonexistent' not found"):
            post_data.get_scalar("nonexistent", "Static_Pressure")

    def test_invalid_scalar_raises(self, post_data):
        with pytest.raises(ValueError, match="Scalar 'bogus' not found"):
            post_data.get_scalar("wall", "bogus")

    def test_scalar_not_in_zone(self, post_data):
        """'far' zone does not have X_Velocity."""
        with pytest.raises(ValueError, match="not found"):
            post_data.get_scalar("far", "X_Velocity")


# ------------------------------------------------------------------
# Points tests
# ------------------------------------------------------------------

class TestGetPoints:
    def test_shape(self, post_data):
        pts = post_data.get_points("wall")
        assert pts.shape == (4, 3)

    def test_writeable_false(self, post_data):
        pts = post_data.get_points("wall")
        assert pts.flags.writeable is False

    def test_values(self, post_data):
        pts = post_data.get_points("wall")
        # First point is (0, 0, 0)
        np.testing.assert_array_equal(pts[0], [0.0, 0.0, 0.0])
        # Second point is (1, 0, 0)
        np.testing.assert_array_equal(pts[1], [1.0, 0.0, 0.0])


# ------------------------------------------------------------------
# Scalar names tests
# ------------------------------------------------------------------

class TestGetScalarNames:
    def test_wall_has_two_scalars(self, post_data):
        names = post_data.get_scalar_names("wall")
        assert "Static_Pressure" in names
        assert "X_Velocity" in names
        assert len(names) == 2

    def test_far_has_one_scalar(self, post_data):
        names = post_data.get_scalar_names("far")
        assert names == ["Static_Pressure"]


# ------------------------------------------------------------------
# Bounds tests
# ------------------------------------------------------------------

class TestGetBounds:
    def test_bounds_keys(self, post_data):
        bounds = post_data.get_bounds("wall")
        assert set(bounds.keys()) == {"xmin", "xmax", "ymin", "ymax", "zmin", "zmax"}

    def test_bounds_values(self, post_data):
        bounds = post_data.get_bounds("wall")
        assert bounds["xmin"] == 0.0
        assert bounds["xmax"] == 1.0
        assert bounds["ymin"] == 0.0
        assert bounds["ymax"] == 1.0
        assert bounds["zmin"] == 0.0
        assert bounds["zmax"] == 0.0


# ------------------------------------------------------------------
# Summary tests
# ------------------------------------------------------------------

class TestGetSummary:
    def test_summary_structure(self, post_data):
        s = post_data.get_summary()
        assert "file_path" in s
        assert "total_points" in s
        assert "total_cells" in s
        assert "zone_count" in s
        assert "zones" in s

    def test_summary_counts(self, post_data):
        s = post_data.get_summary()
        assert s["total_points"] == 8  # 4 + 4
        assert s["total_cells"] == 2   # 1 + 1
        assert s["zone_count"] == 2

    def test_summary_file_path_normalized(self, post_data):
        s = post_data.get_summary()
        assert "\\" not in s["file_path"]
        assert s["file_path"] == "C:/data/test.cgns"

    def test_summary_scalar_mapping(self, post_data):
        s = post_data.get_summary()
        wall_zone = s["zones"][0]
        assert wall_zone["name"] == "wall"
        # Find the Static_Pressure entry - should have standard_name
        sp = [sc for sc in wall_zone["scalars"] if sc["raw_name"] == "Static_Pressure"][0]
        assert sp["standard_name"] == "pressure"
        assert sp["display_name"] == "Pressure"
        assert sp["unit"] == "Pa"


# ------------------------------------------------------------------
# VTK data pass-through
# ------------------------------------------------------------------

class TestGetVtkData:
    def test_returns_same_object(self, post_data):
        mb = make_test_multiblock()
        pd = PostData(mb, "/tmp/test.cgns")
        assert pd.get_vtk_data() is mb

    def test_is_multiblock(self, post_data):
        vtk_data = post_data.get_vtk_data()
        assert isinstance(vtk_data, vtk.vtkMultiBlockDataSet)
