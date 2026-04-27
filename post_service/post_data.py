"""PostData: VTK data thin wrapper with zero-copy numpy access and
physical quantity name mapping (SimGraph2 solver-aware mapping + legacy
aliases for older CFD conventions)."""

import os

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

from post_service.physical_mapping import get_mapping


def _normalize(name: str) -> str:
    """Case-insensitive, delimiter-insensitive key for alias matching.
    Treats '_', '-', ' ' as equivalent and lowercases the result."""
    return name.lower().replace("-", "_").replace(" ", "_").strip("_")


# Legacy aliases: raw names from older CFD conventions (pre-SIDS CGNS,
# custom Tecplot headers) that SimGraph2's solver-aware mapping doesn't
# cover. Kept as a fallback so existing files keep resolving even when
# the solver_id is unknown.
_LEGACY_ALIASES: dict[str, list[str]] = {
    "pressure":             ["Static_Pressure", "p", "PRES"],
    "pressure_coefficient": ["Pressure_Coefficient", "Cp", "CoefPressure", "C_P"],
    "velocity_x":           ["X_Velocity", "Ux", "U_X"],
    "velocity_y":           ["Y_Velocity", "Uy", "U_Y"],
    "velocity_z":           ["Z_Velocity", "Uz", "U_Z"],
    "temperature":          ["Static_Temperature", "T", "TEMP"],
    "mach_number":          ["Mach_Number", "Ma"],
    "density":              ["rho", "DENS"],
    "coordinate_x":         ["x_coordinate", "X", "x"],
    "coordinate_y":         ["y_coordinate", "Y", "y"],
    "coordinate_z":         ["z_coordinate", "Z", "z"],
}

# Reverse lookup: normalized(raw_name) -> standard physical name.
_LEGACY_REVERSE: dict[str, str] = {}
for _std, _aliases in _LEGACY_ALIASES.items():
    for _a in _aliases:
        _LEGACY_REVERSE[_normalize(_a)] = _std
    _LEGACY_REVERSE[_normalize(_std)] = _std


class PostData:
    """VTK data thin wrapper. Holds a reference to vtkMultiBlockDataSet
    (no copy). Provides zero-copy numpy access with writeable=False
    protection and solver-aware physical quantity name resolution."""

    def __init__(self, multiblock: vtk.vtkMultiBlockDataSet, file_path: str,
                 solver_id: str | None = None):
        self._multiblock = multiblock
        self.file_path = os.path.normpath(file_path).replace("\\", "/")
        self.solver_id = solver_id
        self._mapping = get_mapping()
        self._zone_index: dict[str, int] = {}
        self._build_zone_index()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_zone_index(self) -> None:
        """Build mapping from zone name to block index."""
        n = self._multiblock.GetNumberOfBlocks()
        for i in range(n):
            block = self._multiblock.GetBlock(i)
            if block is None:
                continue
            meta = self._multiblock.GetMetaData(i)
            if meta is not None and meta.Has(vtk.vtkCompositeDataSet.NAME()):
                name = meta.Get(vtk.vtkCompositeDataSet.NAME())
            else:
                name = f"Block_{i}"
            self._zone_index[name] = i

    def _get_block(self, zone: str) -> vtk.vtkDataSet:
        """Get VTK block by zone name. Raises ValueError if not found."""
        if zone not in self._zone_index:
            available = list(self._zone_index.keys())
            raise ValueError(
                f"Zone '{zone}' not found. Available zones: {available}"
            )
        return self._multiblock.GetBlock(self._zone_index[zone])

    def _raw_names_for_quantity(self, physical_name: str) -> list[str]:
        """Gather raw names that map to a given physical quantity.

        Preference: current solver first, then every other solver profile,
        then legacy aliases. Callers iterate this list and match against
        the block's actual array names.
        """
        seen: set[str] = set()
        out: list[str] = []

        def _add(name: str) -> None:
            key = _normalize(name)
            if key not in seen:
                seen.add(key)
                out.append(name)

        profiles = self._mapping._solver_profiles
        if self.solver_id and self.solver_id in profiles:
            for e in profiles[self.solver_id].get("mappings", []):
                if e.get("physical_name") == physical_name:
                    _add(e["raw_name"])
        for sid, prof in profiles.items():
            if sid == self.solver_id:
                continue
            for e in prof.get("mappings", []):
                if e.get("physical_name") == physical_name:
                    _add(e["raw_name"])
        for a in _LEGACY_ALIASES.get(physical_name, []):
            _add(a)
        return out

    def _resolve_name(self, zone: str, name: str, block: vtk.vtkDataSet) -> str:
        """Resolve a scalar name (standard or raw) to the actual array name in the block.

        Resolution order:
        1. Direct match
        2. Case/delimiter-insensitive match against block arrays
        3. If *name* is a physical quantity, try raw-name candidates from
           mapping (current solver first) and legacy aliases
        4. Raise ValueError with available names
        """
        point_data = block.GetPointData()
        cell_data = block.GetCellData()

        # 1. Direct match (fast path)
        if point_data.GetArray(name) is not None or cell_data.GetArray(name) is not None:
            return name

        available = self.get_scalar_names(zone)
        target = _normalize(name)

        # 2. Normalized match against actual array names
        for arr_name in available:
            if _normalize(arr_name) == target:
                return arr_name

        # 3. Standard quantity name -> raw name candidates
        is_standard = (
            self._mapping.get_standard_info(name) is not None
            or name in _LEGACY_ALIASES
        )
        if is_standard:
            for cand in self._raw_names_for_quantity(name):
                cand_key = _normalize(cand)
                for arr_name in available:
                    if _normalize(arr_name) == cand_key:
                        return arr_name

        # 4. Not found
        raise ValueError(
            f"Scalar '{name}' not found in zone '{zone}'. "
            f"Available scalars: {available}"
        )

    def _find_standard_name(self, raw_name: str) -> str | None:
        """Reverse lookup: raw array name -> standard physical name, or None."""
        # Solver-aware (authoritative when solver_id known)
        entry = self._mapping.resolve(raw_name, solver_id=self.solver_id)
        if entry and not entry.get("ambiguous"):
            phys = entry.get("physical_name")
            if phys:
                return phys

        # Case/delimiter-insensitive scan across all solver profiles
        target = _normalize(raw_name)
        for prof in self._mapping._solver_profiles.values():
            for e in prof.get("mappings", []):
                if _normalize(e["raw_name"]) == target:
                    phys = e.get("physical_name")
                    if phys:
                        return phys

        # Legacy fallback (covers Static_Pressure / X_Velocity etc.)
        return _LEGACY_REVERSE.get(target)

    def _find_scalar_meta(self, raw_name: str) -> dict:
        """Metadata for a raw scalar: standard_name, display_name, unit,
        plus solver-specific confidence/conversion/ambiguity_risk when
        available."""
        std = self._find_standard_name(raw_name)
        meta: dict = {}
        if std is None:
            return meta
        meta["standard_name"] = std
        info = self._mapping.get_standard_info(std)
        if info:
            if info.get("display_name"):
                meta["display_name"] = info["display_name"]
            if info.get("unit") is not None:
                meta["unit"] = info["unit"]
        entry = self._mapping.resolve(raw_name, solver_id=self.solver_id)
        if entry and not entry.get("ambiguous"):
            for key in ("confidence", "conversion", "ambiguity_risk"):
                val = entry.get(key)
                if val:
                    meta[key] = val
        return meta

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_zones(self) -> list[str]:
        """Return all zone names from multiblock metadata."""
        return list(self._zone_index.keys())

    def get_scalar(self, zone: str, name: str) -> np.ndarray:
        """Zero-copy numpy array for a scalar in the given zone.

        Supports both raw names ('Static_Pressure') and standard names
        ('pressure'). Returned array has writeable=False to protect VTK
        memory.
        """
        block = self._get_block(zone)
        resolved = self._resolve_name(zone, name, block)

        arr = block.GetPointData().GetArray(resolved)
        if arr is None:
            arr = block.GetCellData().GetArray(resolved)
        if arr is None:
            raise ValueError(f"Array '{resolved}' disappeared unexpectedly.")

        np_arr = vtk_to_numpy(arr)
        np_arr.flags.writeable = False
        return np_arr

    def get_points(self, zone: str) -> np.ndarray:
        """Zero-copy node coordinates (N, 3), writeable=False."""
        block = self._get_block(zone)
        pts = block.GetPoints()
        if pts is None:
            raise ValueError(f"Zone '{zone}' has no point coordinates.")
        np_arr = vtk_to_numpy(pts.GetData())
        np_arr.flags.writeable = False
        return np_arr

    def get_scalar_names(self, zone: str) -> list[str]:
        """Return all scalar names (point data + cell data) for a zone."""
        block = self._get_block(zone)
        names: list[str] = []
        seen: set[str] = set()

        for data_obj in (block.GetPointData(), block.GetCellData()):
            for i in range(data_obj.GetNumberOfArrays()):
                arr = data_obj.GetArray(i)
                if arr is None:
                    continue
                arr_name = arr.GetName()
                if arr_name and arr_name not in seen:
                    names.append(arr_name)
                    seen.add(arr_name)
        return names

    def get_bounds(self, zone: str) -> dict:
        """Bounding box for a zone: {xmin, xmax, ymin, ymax, zmin, zmax}."""
        block = self._get_block(zone)
        bounds = block.GetBounds()
        return {
            "xmin": bounds[0],
            "xmax": bounds[1],
            "ymin": bounds[2],
            "ymax": bounds[3],
            "zmin": bounds[4],
            "zmax": bounds[5],
        }

    _VTK_CELL_TYPE_NAMES = {
        3: "line", 5: "triangle", 9: "quad",
        10: "tetra", 12: "hex", 13: "wedge", 14: "pyramid",
        21: "tri6", 22: "tri6", 24: "quad_quadratic",
        25: "hex20", 42: "polyhedron",
    }

    def _get_cell_type_summary(self, block) -> list[dict]:
        """Return [{type: "tetra", count: 12345}, ...] for a VTK block."""
        if not hasattr(block, "GetCellTypesArray"):
            return []
        arr = block.GetCellTypesArray()
        if arr is None or arr.GetNumberOfTuples() == 0:
            return []
        types = vtk_to_numpy(arr)
        unique, counts = np.unique(types, return_counts=True)
        return [
            {"type": self._VTK_CELL_TYPE_NAMES.get(int(t), f"vtk_type_{t}"), "count": int(c)}
            for t, c in zip(unique, counts)
        ]

    def get_summary(self) -> dict:
        """Summary dict with zones, scalars (with mapping info), and mesh counts."""
        zones_info = []
        total_points = 0
        total_cells = 0

        for zone_name in self.get_zones():
            block = self._get_block(zone_name)
            n_points = block.GetNumberOfPoints()
            n_cells = block.GetNumberOfCells()
            total_points += n_points
            total_cells += n_cells

            scalars = []
            for raw_name in self.get_scalar_names(zone_name):
                entry = {"raw_name": raw_name}
                entry.update(self._find_scalar_meta(raw_name))
                scalars.append(entry)

            cell_types = self._get_cell_type_summary(block)

            zones_info.append({
                "name": zone_name,
                "point_count": n_points,
                "cell_count": n_cells,
                "cell_types": cell_types,
                "scalars": scalars,
            })

        return {
            "file_path": self.file_path,
            "solver_id": self.solver_id,
            "total_points": total_points,
            "total_cells": total_cells,
            "zone_count": len(zones_info),
            "zones": zones_info,
        }

    def get_vtk_data(self) -> vtk.vtkMultiBlockDataSet:
        """Return the raw VTK multiblock dataset for heavy algorithms."""
        return self._multiblock
