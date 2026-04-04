"""PostEngine: core computation engine called by both MCP tools and HTTP API."""

import csv
import os

import vtk

from post_service.algorithm_registry import AlgorithmRegistry
from post_service.archive import AnalysisArchive
from post_service.post_data import PostData
from post_service.session import SessionManager


class PostEngine:
    def __init__(self, algorithms_dir: str = None):
        self.session_mgr = SessionManager()
        self.registry = AlgorithmRegistry()
        if algorithms_dir:
            self.registry.scan_and_load(algorithms_dir)

    # File extension → RomtekIODriver reader name mapping
    _READER_MAP = {
        ".cgns": "CGNSReader",
        ".cga": "CGNSReader",
        ".plt": "TecplotReader",
        ".dat": "TecplotReader",
        ".case": "EnsightReader",
        ".vtm": "VTKVTMReader",
        ".vts": "VTKVTSReader",
        ".vtu": "VTKVTUReader",
        ".vtp": "VTKVTPReader",
    }

    def load_file(self, session_id: str, file_path: str) -> dict:
        file_path = os.path.normpath(file_path).replace("\\", "/")
        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}

        # Auto-detect reader from extension
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()
        reader_name = self._READER_MAP.get(ext, "")
        if not reader_name:
            supported = list(self._READER_MAP.keys())
            return {"error": f"Unsupported format: {ext}. Supported: {supported}"}

        try:
            reader = vtk.vtkRomtekIODriver()
            reader.ReadFiles([file_path], reader_name, False)  # list, not string!
            multiblock = reader.getOutPut()
            if multiblock is None:
                return {"error": f"Reader returned no data for: {file_path}"}
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}
        post_data = PostData(multiblock, file_path)
        state = self.session_mgr.get(session_id)
        if state is None:
            state = self.session_mgr.create(session_id)
        state.post_data = post_data
        state.output_dir = os.path.dirname(file_path)
        summary = post_data.get_summary()
        archive_info = AnalysisArchive.check_consistency(file_path)
        summary["archive"] = archive_info
        return summary

    def calculate(self, session_id: str, method: str, params: dict, zone_name: str) -> dict:
        state = self.session_mgr.get(session_id)
        if state is None:
            return {"error": "Session not found. Please load a file first."}
        if state.post_data is None:
            return {"error": "No file loaded. Please use loadFile first."}
        entry = self.registry.get(method)
        if entry is None:
            available = [m["name"] for m in self.registry.list_methods()]
            return {"error": f"Unknown method '{method}'. Available: {available}"}
        merged = {**entry["defaults"], **params}
        try:
            return entry["execute"](state.post_data, merged, zone_name or "")
        except Exception as e:
            return {"error": f"Calculation failed: {e}"}

    def compare(self, session_id: str, source_a: str, source_b: str, **kwargs) -> dict:
        state = self.session_mgr.get(session_id)
        if state is None or state.post_data is None:
            return {"error": "No file loaded."}

        # Phase 1: same-file zone comparison. Parse "zone:scalar" format.
        if ":" not in source_a or ":" not in source_b:
            return {"error": "source_a and source_b must use 'zone:scalar' format (e.g. 'wall:Pressure')."}

        zone_a, scalar_a = source_a.split(":", 1)
        zone_b, scalar_b = source_b.split(":", 1)

        if scalar_a != scalar_b:
            return {"error": f"Scalar mismatch: '{scalar_a}' vs '{scalar_b}'. Phase 1 only supports comparing the same scalar across zones."}

        entry = self.registry.get("compare")
        if entry is None:
            return {"error": "Compare algorithm not loaded."}

        params = {**entry["defaults"], "scalar": scalar_a, "zone_a": zone_a, "zone_b": zone_b}
        try:
            return entry["execute"](state.post_data, params, "")
        except Exception as e:
            return {"error": f"Compare failed: {e}"}

    def export_data(self, session_id: str, zone: str, scalars: list, format: str = "csv") -> dict:
        state = self.session_mgr.get(session_id)
        if state is None or state.post_data is None:
            return {"error": "No file loaded."}
        pd = state.post_data
        if format == "csv":
            points = pd.get_points(zone)
            output_path = os.path.join(state.output_dir, f"{zone}_export.csv")
            output_path = os.path.normpath(output_path).replace("\\", "/")
            with open(output_path, "w", newline="") as f:
                writer = csv.writer(f)
                header = ["x", "y", "z"] + scalars
                writer.writerow(header)
                scalar_arrays = {}
                for s in scalars:
                    try:
                        scalar_arrays[s] = pd.get_scalar(zone, s)
                    except ValueError:
                        return {"error": f"Scalar '{s}' not found in zone '{zone}'"}
                for i in range(len(points)):
                    row = list(points[i]) + [float(scalar_arrays[s][i]) for s in scalars]
                    writer.writerow(row)
            return {
                "type": "file",
                "summary": f"Exported {zone} ({len(scalars)} scalars, {len(points)} points) to {output_path}",
                "data": {"file_path": output_path, "format": format},
                "output_files": [output_path],
            }
        return {"error": f"Unsupported format: {format}"}

    def list_files(self, directory: str, suffix: str = None) -> dict:
        directory = os.path.normpath(directory).replace("\\", "/")
        if not os.path.isdir(directory):
            return {"error": f"Directory not found: {directory}"}
        files = []
        for f in sorted(os.listdir(directory)):
            full = os.path.join(directory, f)
            if not os.path.isfile(full):
                continue
            if suffix and not f.endswith(suffix):
                continue
            files.append(os.path.normpath(full).replace("\\", "/"))
        return {"files": files, "count": len(files), "directory": directory}

    def get_method_template(self, method: str = None) -> dict:
        if method:
            entry = self.registry.get(method)
            if entry is None:
                return {"error": f"Unknown method: {method}"}
            return {
                "method": entry["name"],
                "description": entry["description"],
                "defaults": entry["defaults"],
            }
        return {"methods": self.registry.list_methods()}

    def save_archive(self, session_id, method, zone, params, result, note=""):
        """Save an analysis result entry to the archive (user-triggered only)."""
        state = self.session_mgr.get(session_id)
        if state is None or state.post_data is None:
            return {"error": "No file loaded."}
        path = AnalysisArchive.save_entry(
            state.post_data.file_path, method, zone, params, result, note
        )
        archive = AnalysisArchive.load(state.post_data.file_path)
        return {
            "summary": f"已保存到 {path}",
            "entries_count": len(archive["entries"]),
        }

    def get_archive(self, session_id):
        """Retrieve the archive history for the currently loaded file."""
        state = self.session_mgr.get(session_id)
        if state is None or state.post_data is None:
            return {"error": "No file loaded."}
        archive = AnalysisArchive.load(state.post_data.file_path)
        if archive is None:
            return {"summary": "该文件没有历史分析存档", "entries": []}
        return {
            "summary": f"找到 {len(archive['entries'])} 条历史记录",
            "entries": archive["entries"],
        }

    def get_mesh_geometry(self, session_id: str, zone: str):
        """Return mesh point coordinates as raw bytes, or None."""
        state = self.session_mgr.get(session_id)
        if state is None or state.post_data is None:
            return None
        try:
            return state.post_data.get_points(zone).tobytes()
        except ValueError:
            return None

    def get_scalar_data(self, session_id: str, zone: str, name: str):
        """Return scalar array as raw bytes, or None."""
        state = self.session_mgr.get(session_id)
        if state is None or state.post_data is None:
            return None
        try:
            return state.post_data.get_scalar(zone, name).tobytes()
        except ValueError:
            return None
