import os
import threading
import time

import vtk

from post_service.post_data import PostData


class FrameSequence:
    """Lazy-loading multi-frame container. Holds reader reference, loads frames on demand."""

    def __init__(self, reader, file_path: str, frame_count: int, time_labels: list[str],
                 max_cache: int = 50, solver_id: str | None = None):
        self.reader = reader  # vtk.vtkRomtekIODriver, kept alive
        self.file_path = file_path
        self.frame_count = frame_count
        self.time_labels = time_labels
        self.solver_id = solver_id
        self._lock = threading.Lock()
        self._cache: dict[int, PostData] = {}
        self._cache_order: list[int] = []
        self._max_cache = max_cache
        self._global_ranges: dict | None = None  # cached global scalar ranges
        self._preloading = False
        self._preload_done = False

    def get_frame(self, index: int) -> PostData:
        """Load a single frame on demand with LRU cache."""
        if index < 0 or index >= self.frame_count:
            raise IndexError(f"Frame index {index} out of range [0, {self.frame_count})")

        with self._lock:
            if index in self._cache:
                self._cache_order.remove(index)
                self._cache_order.append(index)
                return self._cache[index]

            self.reader.SetOutPutByTimeIndex(index)
            mb = self.reader.getOutPut()
            mb_copy = vtk.vtkMultiBlockDataSet()
            mb_copy.DeepCopy(mb)
            pd = PostData(mb_copy, self.file_path, solver_id=self.solver_id)

            if len(self._cache) >= self._max_cache:
                oldest = self._cache_order.pop(0)
                del self._cache[oldest]
            self._cache[index] = pd
            self._cache_order.append(index)
            return pd

    def load_all_multiblocks(self) -> list:
        """Load ALL frames' multiblocks for algorithm data bridge.

        Returns list of vtkMultiBlockDataSet. Used during algorithm execution;
        caller should not hold references long-term.
        """
        with self._lock:
            result = []
            for i in range(self.frame_count):
                self.reader.SetOutPutByTimeIndex(i)
                mb = self.reader.getOutPut()
                mb_copy = vtk.vtkMultiBlockDataSet()
                mb_copy.DeepCopy(mb)
                result.append(mb_copy)
            return result

    def set_max_cache(self, n: int):
        """Update max cache size. Evicts oldest frames if shrinking."""
        self._max_cache = max(1, n)
        with self._lock:
            while len(self._cache) > self._max_cache:
                oldest = self._cache_order.pop(0)
                del self._cache[oldest]

    def get_global_scalar_ranges(self) -> dict:
        """Compute global min/max for each scalar across ALL frames.

        Returns: {zone_name: {scalar_name: [min, max]}}
        Cached after first computation. Releases lock between frames so
        get_frame() requests can interleave. Also populates PostData cache
        for each frame during the scan (avoids a second pass).
        """
        if self._global_ranges is not None:
            return self._global_ranges

        ranges: dict[str, dict[str, list[float]]] = {}
        for i in range(self.frame_count):
            with self._lock:
                self.reader.SetOutPutByTimeIndex(i)
                mb = self.reader.getOutPut()

                # Also populate PostData cache while we have the reader output
                if i not in self._cache and len(self._cache) < self._max_cache:
                    mb_copy = vtk.vtkMultiBlockDataSet()
                    mb_copy.DeepCopy(mb)
                    self._cache[i] = PostData(mb_copy, self.file_path, solver_id=self.solver_id)
                    self._cache_order.append(i)

                # Extract ranges (fast — just reads array min/max)
                for bi in range(mb.GetNumberOfBlocks()):
                    block = mb.GetBlock(bi)
                    if block is None:
                        continue
                    meta = mb.GetMetaData(bi)
                    if meta and meta.Has(vtk.vtkCompositeDataSet.NAME()):
                        zone_name = meta.Get(vtk.vtkCompositeDataSet.NAME())
                    else:
                        zone_name = f"Block_{bi}"
                    if zone_name not in ranges:
                        ranges[zone_name] = {}
                    for data_obj in (block.GetPointData(), block.GetCellData()):
                        for ai in range(data_obj.GetNumberOfArrays()):
                            arr = data_obj.GetArray(ai)
                            if arr is None:
                                continue
                            name = arr.GetName()
                            if not name:
                                continue
                            lo, hi = arr.GetRange()
                            if name in ranges[zone_name]:
                                prev = ranges[zone_name][name]
                                prev[0] = min(prev[0], lo)
                                prev[1] = max(prev[1], hi)
                            else:
                                ranges[zone_name][name] = [lo, hi]
        self._global_ranges = ranges
        self._preload_done = True
        return ranges

    def start_preload(self):
        """Start background preload: computes global scalar ranges + fills PostData cache.
        Non-blocking — spawns a daemon thread. Lock is released between frames so
        on-demand get_frame() calls can interleave with the preload."""
        if self._preloading or self._preload_done:
            return
        self._preloading = True
        thread = threading.Thread(target=self._preload_worker, daemon=True)
        thread.start()

    def _preload_worker(self):
        """Background: compute global ranges (which also fills PostData cache)."""
        try:
            self.get_global_scalar_ranges()
            print(f"[FrameSequence] Preload complete: {len(self._cache)}/{self.frame_count} frames cached")
        except Exception as e:
            print(f"[FrameSequence] Preload error: {e}")
        finally:
            self._preloading = False

    def close(self):
        """Release reader and cache to free file handles and memory."""
        self._cache.clear()
        self._cache_order.clear()
        self.reader = None


class MultiFileFrameSequence:
    """Frame sequence where each file in a directory is one frame.

    Same interface as FrameSequence so Session/HTTP API code works unchanged.
    """

    def __init__(self, file_paths: list[str], reader_names: list[str],
                 virtual_path: str, max_cache: int = 50,
                 solver_id: str | None = None):
        self.file_paths = file_paths          # one path per frame
        self.reader_names = reader_names      # reader name per frame
        self.file_path = virtual_path         # directory path, used as session key
        self.frame_count = len(file_paths)
        self.time_labels = [os.path.splitext(os.path.basename(fp))[0] for fp in file_paths]
        self.reader = None                    # no single reader
        self.solver_id = solver_id
        self._lock = threading.Lock()
        self._cache: dict[int, PostData] = {}
        self._cache_order: list[int] = []
        self._max_cache = max_cache
        self._global_ranges: dict | None = None
        self._preloading = False
        self._preload_done = False

    def _read_file(self, index: int):
        """Read a single file and return a deep-copied multiblock."""
        reader = vtk.vtkRomtekIODriver()
        reader.ReadFiles([self.file_paths[index]], self.reader_names[index], False)
        mb = reader.getOutPut()
        if mb is None:
            return None
        mb_copy = vtk.vtkMultiBlockDataSet()
        mb_copy.DeepCopy(mb)
        return mb_copy

    def get_frame(self, index: int) -> PostData:
        """Load frame (= file) on demand. Double-check locking for parallel reads."""
        if index < 0 or index >= self.frame_count:
            raise IndexError(f"Frame index {index} out of range [0, {self.frame_count})")

        with self._lock:
            if index in self._cache:
                self._cache_order.remove(index)
                self._cache_order.append(index)
                return self._cache[index]

        # Read outside lock — each file has its own reader, no shared state
        mb = self._read_file(index)
        if mb is None:
            raise RuntimeError(f"Failed to read frame {index}: {self.file_paths[index]}")
        pd = PostData(mb, self.file_path, solver_id=self.solver_id)

        with self._lock:
            if index in self._cache:
                self._cache_order.remove(index)
                self._cache_order.append(index)
                return self._cache[index]
            if len(self._cache) >= self._max_cache:
                oldest = self._cache_order.pop(0)
                del self._cache[oldest]
            self._cache[index] = pd
            self._cache_order.append(index)
            return pd

    def load_all_multiblocks(self) -> list:
        """Load ALL frames' multiblocks for algorithm data bridge."""
        result = []
        for i in range(self.frame_count):
            mb = self._read_file(i)
            if mb is not None:
                result.append(mb)
        return result

    def set_max_cache(self, n: int):
        self._max_cache = max(1, n)
        with self._lock:
            while len(self._cache) > self._max_cache:
                oldest = self._cache_order.pop(0)
                del self._cache[oldest]

    def get_global_scalar_ranges(self) -> dict:
        """Compute global min/max for each scalar across ALL frames (files)."""
        if self._global_ranges is not None:
            return self._global_ranges

        ranges: dict[str, dict[str, list[float]]] = {}
        for i in range(self.frame_count):
            mb = self._read_file(i)
            if mb is None:
                continue

            with self._lock:
                if i not in self._cache and len(self._cache) < self._max_cache:
                    pd = PostData(mb, self.file_path, solver_id=self.solver_id)
                    self._cache[i] = pd
                    self._cache_order.append(i)

            for bi in range(mb.GetNumberOfBlocks()):
                block = mb.GetBlock(bi)
                if block is None:
                    continue
                meta = mb.GetMetaData(bi)
                if meta and meta.Has(vtk.vtkCompositeDataSet.NAME()):
                    zone_name = meta.Get(vtk.vtkCompositeDataSet.NAME())
                else:
                    zone_name = f"Block_{bi}"
                if zone_name not in ranges:
                    ranges[zone_name] = {}
                for data_obj in (block.GetPointData(), block.GetCellData()):
                    for ai in range(data_obj.GetNumberOfArrays()):
                        arr = data_obj.GetArray(ai)
                        if arr is None:
                            continue
                        name = arr.GetName()
                        if not name:
                            continue
                        lo, hi = arr.GetRange()
                        if name in ranges[zone_name]:
                            prev = ranges[zone_name][name]
                            prev[0] = min(prev[0], lo)
                            prev[1] = max(prev[1], hi)
                        else:
                            ranges[zone_name][name] = [lo, hi]

        self._global_ranges = ranges
        self._preload_done = True
        return ranges

    def start_preload(self):
        if self._preloading or self._preload_done:
            return
        self._preloading = True
        thread = threading.Thread(target=self._preload_worker, daemon=True)
        thread.start()

    def _preload_worker(self):
        try:
            self.get_global_scalar_ranges()
            print(f"[MultiFileFrameSequence] Preload done: {len(self._cache)}/{self.frame_count} cached")
        except Exception as e:
            print(f"[MultiFileFrameSequence] Preload error: {e}")
        finally:
            self._preloading = False

    def close(self):
        self._cache.clear()
        self._cache_order.clear()


class SessionState:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self._post_data_map = {}    # file_path -> PostData (frame 0)
        self._sequence_map = {}     # file_path -> FrameSequence
        self._active_file = None    # current active file path
        self.output_dir = None      # auto-set to file's directory
        self.geometry_results = {}  # result_id -> vtkDataSet (geometry algorithm outputs)
        self._surface_cache = {}    # (norm_file, zone, frame) -> vtp_bytes
        self._surface_order = []    # LRU order for surface cache
        self._surface_cache_max = 500
        self.created_at = time.time()
        self.last_active = time.time()

    @property
    def post_data(self):
        """Active file's PostData (backward compatible)."""
        if self._active_file:
            return self._post_data_map.get(self._active_file)
        return None

    @post_data.setter
    def post_data(self, value):
        if value is None:
            self._active_file = None
        else:
            self._active_file = value.file_path
            self._post_data_map[value.file_path] = value

    def get_post_data(self, file_path=None, frame=None):
        """Get PostData for a specific file and optional frame index."""
        path = file_path or self._active_file
        if path:
            normalized = os.path.normpath(path).replace("\\", "/")
            if frame is not None and normalized in self._sequence_map:
                return self._sequence_map[normalized].get_frame(frame)
            return self._post_data_map.get(normalized)
        return None

    def get_sequence(self, file_path=None) -> FrameSequence | None:
        """Get FrameSequence for a file."""
        path = file_path or self._active_file
        if path:
            normalized = os.path.normpath(path).replace("\\", "/")
            return self._sequence_map.get(normalized)
        return None

    def get_cached_surface(self, file_key: str, zone: str, frame: int) -> bytes | None:
        """Get cached VTP bytes for a surface, or None on miss."""
        key = (file_key, zone, frame)
        if key in self._surface_cache:
            self._surface_order.remove(key)
            self._surface_order.append(key)
            return self._surface_cache[key]
        return None

    def put_cached_surface(self, file_key: str, zone: str, frame: int, vtp_bytes: bytes):
        """Cache VTP surface bytes with LRU eviction."""
        key = (file_key, zone, frame)
        if key in self._surface_cache:
            self._surface_order.remove(key)
        elif len(self._surface_cache) >= self._surface_cache_max:
            oldest = self._surface_order.pop(0)
            del self._surface_cache[oldest]
        self._surface_cache[key] = vtp_bytes
        self._surface_order.append(key)

    def touch(self):
        self.last_active = time.time()


class SessionManager:
    def __init__(self, timeout_seconds: int = 3600):
        self._sessions = {}
        self._timeout = timeout_seconds

    def create(self, session_id: str) -> SessionState:
        state = SessionState(session_id)
        self._sessions[session_id] = state
        return state

    def get(self, session_id: str):
        state = self._sessions.get(session_id)
        if state:
            state.touch()
        return state

    def destroy(self, session_id: str):
        state = self._sessions.pop(session_id, None)
        if state:
            for seq in state._sequence_map.values():
                seq.close()
            state._sequence_map.clear()
            state._post_data_map.clear()
            state._active_file = None

    def cleanup_expired(self):
        now = time.time()
        expired = [sid for sid, s in self._sessions.items()
                   if now - s.last_active > self._timeout]
        for sid in expired:
            self.destroy(sid)
