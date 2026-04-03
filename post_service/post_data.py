"""PostData: VTK data thin wrapper with zero-copy numpy access and physical quantity name mapping."""

import json
import os

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy


# Load physical mapping once at module level
_CONFIG_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "config")
).replace("\\", "/")

_MAPPING_PATH = _CONFIG_DIR + "/physical_mapping.json"

with open(_MAPPING_PATH, "r", encoding="utf-8") as _f:
    _PHYSICAL_MAPPING: dict = json.load(_f)

# Build reverse alias lookup: raw_name -> standard_name
_ALIAS_TO_STANDARD: dict[str, str] = {}
for _std_name, _entry in _PHYSICAL_MAPPING.items():
    for _alias in _entry["aliases"]:
        _ALIAS_TO_STANDARD[_alias] = _std_name


class PostData:
    """VTK data thin wrapper. Holds a reference to vtkMultiBlockDataSet (no copy).
    Provides zero-copy numpy access with writeable=False protection and
    physical quantity name resolution via mapping."""

    def __init__(self, multiblock: vtk.vtkMultiBlockDataSet, file_path: str):
        self._multiblock = multiblock
        self.file_path = os.path.normpath(file_path).replace("\\", "/")
        self._mapping = _PHYSICAL_MAPPING
        self._alias_to_standard = _ALIAS_TO_STANDARD
        # Build zone index: name -> block index
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

    def _resolve_name(self, zone: str, name: str, block: vtk.vtkDataSet) -> str:
        """Resolve a scalar name (standard or raw) to the actual array name in the block.

        Resolution order:
        1. Direct match in point data or cell data
        2. If name is a standard name, try each alias from mapping
        3. Raise ValueError with available names
        """
        point_data = block.GetPointData()
        cell_data = block.GetCellData()

        # 1. Direct match
        if point_data.GetArray(name) is not None or cell_data.GetArray(name) is not None:
            return name

        # 2. Standard name -> try aliases
        if name in self._mapping:
            for alias in self._mapping[name]["aliases"]:
                if point_data.GetArray(alias) is not None or cell_data.GetArray(alias) is not None:
                    return alias

        # 3. Not found
        available = self.get_scalar_names(zone)
        raise ValueError(
            f"Scalar '{name}' not found in zone '{zone}'. "
            f"Available scalars: {available}"
        )

    def _find_standard_name(self, raw_name: str) -> str | None:
        """Reverse lookup: raw array name -> standard name, or None if not mapped."""
        return self._alias_to_standard.get(raw_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_zones(self) -> list[str]:
        """Return all zone names from multiblock metadata."""
        return list(self._zone_index.keys())

    def get_scalar(self, zone: str, name: str) -> np.ndarray:
        """Zero-copy numpy array for a scalar in the given zone.

        Supports both raw names ('Static_Pressure') and standard names ('pressure').
        Returned array has writeable=False to protect VTK memory.
        """
        block = self._get_block(zone)
        resolved = self._resolve_name(zone, name, block)

        # Try point data first, then cell data
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
                std = self._find_standard_name(raw_name)
                if std is not None:
                    m = self._mapping[std]
                    entry["standard_name"] = std
                    entry["display_name"] = m["display_name"]
                    entry["unit"] = m["unit"]
                scalars.append(entry)

            zones_info.append({
                "name": zone_name,
                "point_count": n_points,
                "cell_count": n_cells,
                "scalars": scalars,
            })

        return {
            "file_path": self.file_path,
            "total_points": total_points,
            "total_cells": total_cells,
            "zone_count": len(zones_info),
            "zones": zones_info,
        }

    def get_vtk_data(self) -> vtk.vtkMultiBlockDataSet:
        """Return the raw VTK multiblock dataset for heavy algorithms."""
        return self._multiblock
