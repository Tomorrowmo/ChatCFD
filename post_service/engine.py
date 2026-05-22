"""PostEngine: core computation engine called by both MCP tools and HTTP API."""

import csv
import os
import re

import vtk

from post_service.algorithm_registry import AlgorithmRegistry
from post_service.archive import AnalysisArchive
from post_service.post_data import PostData
from post_service.session import FrameSequence, MultiFileFrameSequence, SessionManager


def _session_output_dir(file_path: str, session_id: str) -> str:
    """Per-session product directory: <file dir>/<file stem>/<session seg>.

    Calculation outputs (.vtp/.png/.gif/.csv) go here. The trailing session
    segment isolates concurrent terminals — two sessions loading the same
    file no longer overwrite each other's products.
    """
    stem = os.path.splitext(os.path.basename(file_path))[0]
    seg = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "default") or "default"
    return os.path.normpath(
        os.path.join(os.path.dirname(file_path), stem, seg)
    ).replace("\\", "/")


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
    # Filename (no extension) → reader mapping (for formats identified by filename)
    _FILENAME_READER_MAP = {
        "d3plot": "VTKD3PlotReader",
        "controlDict": "OpenFoamReader",
    }

    # Reader name → SimGraph2 solver_id. Drives physical-quantity mapping
    # in PostData. VTK/Ensight readers have no canonical source solver, so
    # they fall back to None (legacy alias layer still catches common names).
    _READER_SOLVER_MAP = {
        "CGNSReader":       "cgns",
        "TecplotReader":    "tecplot",
        "VTKD3PlotReader":  "lsdyna",
        "OpenFoamReader":   "openfoam_incompressible",
    }

    def _reader_to_solver_id(self, reader_name: str) -> str | None:
        """Map RomtekIODriver reader name to SimGraph2 solver_id.
        OpenFOAM defaults to incompressible (most common); compressible
        files need explicit override from the user."""
        return self._READER_SOLVER_MAP.get(reader_name)

    def _is_supported_file(self, file_path: str) -> bool:
        """Check if a file is a supported CFD format."""
        basename = os.path.basename(file_path)
        filename_no_ext = os.path.splitext(basename)[0]
        if basename in self._FILENAME_READER_MAP or filename_no_ext in self._FILENAME_READER_MAP:
            return True
        _, ext = os.path.splitext(file_path)
        return ext.lower() in self._READER_MAP

    def load_directory(self, session_id: str, dir_path: str) -> dict:
        """Load all supported CFD files from a directory as a single multi-frame sequence.

        Each file becomes one frame. Returns the same format as load_file() so the
        agent/frontend treat it identically to a multi-frame single file.
        """
        dir_path = os.path.normpath(dir_path).replace("\\", "/")
        if not os.path.isdir(dir_path):
            return {"error": f"Directory not found: {dir_path}"}

        # Collect supported files with reader names
        targets = []
        reader_names = []
        for f in sorted(os.listdir(dir_path)):
            full = os.path.normpath(os.path.join(dir_path, f)).replace("\\", "/")
            if not os.path.isfile(full):
                continue
            basename = os.path.basename(full)
            filename_no_ext = os.path.splitext(basename)[0]
            rn = self._FILENAME_READER_MAP.get(basename, "") or \
                 self._FILENAME_READER_MAP.get(filename_no_ext, "")
            if not rn:
                _, ext = os.path.splitext(full)
                rn = self._READER_MAP.get(ext.lower(), "")
            if rn:
                targets.append(full)
                reader_names.append(rn)

        if not targets:
            supported = list(self._READER_MAP.keys()) + list(self._FILENAME_READER_MAP.keys())
            return {"error": f"No supported files in '{dir_path}'. Supported formats: {supported}"}

        # All files share the same solver when they share the reader, which
        # is the common case (a directory of .cgns / .plt / .vtu). When they
        # differ (rare), fall back to the first file's solver — PostData's
        # legacy alias layer catches the others.
        solver_id = self._reader_to_solver_id(reader_names[0])
        sequence = MultiFileFrameSequence(
            targets, reader_names, dir_path, solver_id=solver_id,
        )

        # Load frame 0 for immediate use
        try:
            frame0 = sequence.get_frame(0)
        except Exception as e:
            return {"error": f"Failed to read first file: {e}"}

        # Start background preload
        if sequence.frame_count > 1:
            sequence.start_preload()

        # Register in session
        state = self.session_mgr.get(session_id)
        if state is None:
            state = self.session_mgr.create(session_id)
        state.post_data = frame0
        state._sequence_map[dir_path] = sequence
        state.output_dir = _session_output_dir(dir_path, session_id)

        # Return single-file compatible summary
        summary = frame0.get_summary()
        summary["file_path"] = dir_path
        summary["frame_count"] = sequence.frame_count
        summary["time_labels"] = sequence.time_labels
        print(f"[Engine.load_directory] {dir_path}: {sequence.frame_count} files as frames")
        return summary

    def load_file(self, session_id: str, file_path: str) -> dict:
        file_path = os.path.normpath(file_path).replace("\\", "/")

        # If path is a directory, load all supported files within it
        if os.path.isdir(file_path):
            return self.load_directory(session_id, file_path)

        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}

        # Auto-detect reader: check filename first, then extension
        basename = os.path.basename(file_path)
        filename_no_ext = os.path.splitext(basename)[0]
        reader_name = self._FILENAME_READER_MAP.get(basename, "") or \
                      self._FILENAME_READER_MAP.get(filename_no_ext, "")
        if not reader_name:
            _, ext = os.path.splitext(file_path)
            ext = ext.lower()
            reader_name = self._READER_MAP.get(ext, "")
        if not reader_name:
            supported = list(self._READER_MAP.keys()) + list(self._FILENAME_READER_MAP.keys())
            return {"error": f"Unsupported format: '{basename}'. Supported: {supported}"}

        try:
            reader = vtk.vtkRomtekIODriver()
            reader.ReadFiles([file_path], reader_name, False)
            multiblock = reader.getOutPut()
            if multiblock is None:
                return {"error": f"Reader returned no data for: {file_path}"}
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

        # Multi-frame support: detect time steps
        time_count = 1
        time_labels = ["0"]
        try:
            tc = reader.getTimeCount()
            if tc > 0:
                time_count = tc
            if time_count > 1:
                try:
                    tl = reader.getTimeLables()
                    time_labels = list(tl) if tl else [str(i) for i in range(time_count)]
                except Exception:
                    time_labels = [str(i) for i in range(time_count)]
                # Pad if length mismatch
                if len(time_labels) != time_count:
                    time_labels = [
                        time_labels[i] if i < len(time_labels) else str(i)
                        for i in range(time_count)
                    ]
        except Exception:
            pass  # reader doesn't support getTimeCount — single frame

        # Create FrameSequence (lazy — reader kept alive, frames loaded on demand)
        solver_id = self._reader_to_solver_id(reader_name)
        sequence = FrameSequence(
            reader, file_path, time_count, time_labels, solver_id=solver_id,
        )

        # Load frame 0 for immediate use
        frame0 = sequence.get_frame(0)

        # Start background preload for multi-frame files (fills PostData cache + scalar ranges)
        if time_count > 1:
            sequence.start_preload()

        state = self.session_mgr.get(session_id)
        if state is None:
            state = self.session_mgr.create(session_id)
        state.post_data = frame0
        state._sequence_map[file_path] = sequence

        state.output_dir = _session_output_dir(file_path, session_id)
        summary = frame0.get_summary()
        summary["frame_count"] = time_count
        summary["time_labels"] = time_labels
        archive_info = AnalysisArchive.check_consistency(file_path)
        summary["archive"] = archive_info
        print(f"[Engine.load_file] Loaded {file_path}: {time_count} frames")
        return summary

    def calculate(self, session_id: str, method: str, params: dict, zone_name: str) -> dict:
        import traceback
        print(f"[Engine.calculate] method={method}, params={params}, zone_name={zone_name}, session_id={session_id}")
        state = self.session_mgr.get(session_id)
        if state is None:
            print(f"[Engine.calculate] ERROR: Session '{session_id}' not found")
            return {"error": "Session not found. Please load a file first."}
        if state.post_data is None:
            print(f"[Engine.calculate] ERROR: No file loaded in session '{session_id}'")
            return {"error": "No file loaded. Please use loadFile first."}
        entry = self.registry.get(method)
        if entry is None:
            available = [m["name"] for m in self.registry.list_methods()]
            print(f"[Engine.calculate] ERROR: Unknown method '{method}'. Available: {available}")
            return {"error": f"Unknown method '{method}'. Available: {available}"}
        merged = {**entry["defaults"], **params}
        print(f"[Engine.calculate] merged params: {merged}")
        try:
            # Pass sequence + frame_count as kwargs for multi-frame algorithms
            sequence = state.get_sequence(state._active_file)
            frame_count = sequence.frame_count if sequence else 1
            time_labels = sequence.time_labels if sequence else ["0"]
            result = entry["execute"](
                state.post_data, merged, zone_name or "",
                sequence=sequence, frame_count=frame_count, time_labels=time_labels,
                output_dir=state.output_dir,
            )
        except Exception as e:
            traceback.print_exc()
            return {"error": f"Calculation failed: {e}"}

        if isinstance(result, dict) and result.get("error"):
            print(f"[Engine.calculate] Algorithm returned error: {result['error']}")
        else:
            print(f"[Engine.calculate] Success: type={result.get('type')}, summary={str(result.get('summary', ''))[:100]}")

        # Auto-store geometry results in session for HTTP API access
        if isinstance(result, dict) and result.get("type") == "geometry":
            vtk_output = result.pop("_vtk_output", None)
            if vtk_output is not None:
                result_id = result.get("data", {}).get("result_id")
                if result_id:
                    state.geometry_results[result_id] = vtk_output

        return result

    def compare(self, session_id: str, source_a: str, source_b: str, **kwargs) -> dict:
        state = self.session_mgr.get(session_id)
        if state is None or state.post_data is None:
            return {"error": "No file loaded."}

        if ":" not in source_a or ":" not in source_b:
            return {"error": "source_a and source_b must use 'zone:scalar' format (e.g. 'wall:Pressure')."}

        zone_a, scalar_a = source_a.split(":", 1)
        zone_b, scalar_b = source_b.split(":", 1)

        if scalar_a != scalar_b:
            return {"error": f"Scalar mismatch: '{scalar_a}' vs '{scalar_b}'."}

        # Cross-file: get post_data for file_b
        file_b = kwargs.get("file_b", "")
        pd_b = None
        if file_b:
            pd_b = state.get_post_data(file_b)
            if pd_b is None:
                return {"error": f"File '{file_b}' not loaded. Call loadFile first."}

        entry = self.registry.get("compare")
        if entry is None:
            return {"error": "Compare algorithm not loaded."}

        params = {**entry["defaults"], "scalar": scalar_a, "zone_a": zone_a, "zone_b": zone_b}
        try:
            if pd_b:
                return entry["execute"](state.post_data, params, "", post_data_b=pd_b)
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
            os.makedirs(state.output_dir, exist_ok=True)
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

    def list_files(self, directory: str, suffix: str = None,
                   keyword: str = None, recursive: bool = False) -> dict:
        directory = os.path.normpath(directory).replace("\\", "/")
        if not os.path.isdir(directory):
            return {"error": f"Directory not found: {directory}"}
        files = []
        if recursive:
            max_results = 200
            for root, _dirs, fnames in os.walk(directory):
                for f in sorted(fnames):
                    if suffix and not f.endswith(suffix):
                        continue
                    if keyword and keyword.lower() not in f.lower():
                        continue
                    full = os.path.normpath(os.path.join(root, f)).replace("\\", "/")
                    files.append(full)
                    if len(files) >= max_results:
                        break
                if len(files) >= max_results:
                    break
        else:
            for f in sorted(os.listdir(directory)):
                full = os.path.join(directory, f)
                if not os.path.isfile(full):
                    continue
                if suffix and not f.endswith(suffix):
                    continue
                if keyword and keyword.lower() not in f.lower():
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
