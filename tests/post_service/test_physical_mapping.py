"""Tests for PhysicalMapping (ported from SimGraph2)."""

import pytest

from post_service.physical_mapping import PhysicalMapping, get_mapping


@pytest.fixture(scope="module")
def pm() -> PhysicalMapping:
    return get_mapping()


class TestResolveWithSolver:
    def test_p_openfoam_incompressible(self, pm: PhysicalMapping):
        result = pm.resolve("p", solver_id="openfoam_incompressible")
        assert result is not None
        assert result["physical_name"] == "pressure_kinematic"
        assert result["confidence"] == "HIGH"

    def test_p_openfoam_compressible(self, pm: PhysicalMapping):
        result = pm.resolve("p", solver_id="openfoam_compressible")
        assert result is not None
        assert result["physical_name"] == "pressure"

    def test_pressure_fluent(self, pm: PhysicalMapping):
        result = pm.resolve("pressure", solver_id="fluent")
        assert result is not None
        assert result["physical_name"] == "pressure"

    def test_U_openfoam(self, pm: PhysicalMapping):
        result = pm.resolve("U", solver_id="openfoam_incompressible")
        assert result is not None
        assert "velocity" in result["physical_name"]

    def test_unknown_variable(self, pm: PhysicalMapping):
        assert pm.resolve("nonexistent_var_xyz", solver_id="openfoam_incompressible") is None

    def test_unknown_solver(self, pm: PhysicalMapping):
        assert pm.resolve("p", solver_id="unknown_solver_xyz") is None


class TestResolveWithoutSolver:
    def test_p_ambiguous(self, pm: PhysicalMapping):
        result = pm.resolve("p")
        assert result is not None
        assert result.get("ambiguous") is True
        phys_names = {c["physical_name"] for c in result["candidates"]}
        assert "pressure_kinematic" in phys_names
        assert "pressure" in phys_names

    def test_k_unambiguous(self, pm: PhysicalMapping):
        result = pm.resolve("k")
        assert result is not None
        assert result.get("ambiguous") is not True
        assert result["physical_name"] == "tke"


class TestDisambiguateByRange:
    def test_pa_range_is_pressure(self, pm: PhysicalMapping):
        result = pm.disambiguate_by_range("p", min_val=95000, max_val=110000)
        assert result is not None
        assert result["physical_name"] == "pressure"

    def test_kinematic_range_is_pressure_kinematic(self, pm: PhysicalMapping):
        result = pm.disambiguate_by_range("p", min_val=-100, max_val=500)
        assert result is not None
        assert result["physical_name"] == "pressure_kinematic"

    def test_unknown_raw_name(self, pm: PhysicalMapping):
        assert pm.disambiguate_by_range("nonexistent_xyz", min_val=0, max_val=1) is None


class TestGetStandardInfo:
    def test_pressure(self, pm: PhysicalMapping):
        info = pm.get_standard_info("pressure")
        assert info is not None
        assert info["unit"] == "Pa"
        assert info["type"] == "scalar"

    def test_tke(self, pm: PhysicalMapping):
        info = pm.get_standard_info("tke")
        assert info is not None
        assert info["unit"] == "m\u00b2/s\u00b2"

    def test_unknown(self, pm: PhysicalMapping):
        assert pm.get_standard_info("nonexistent_qty") is None


class TestGetAllRawNames:
    def test_openfoam_incompressible(self, pm: PhysicalMapping):
        names = pm.get_all_raw_names("openfoam_incompressible")
        assert isinstance(names, list)
        assert "p" in names
        assert "U" in names

    def test_unknown_solver(self, pm: PhysicalMapping):
        assert pm.get_all_raw_names("nonexistent_solver") == []
