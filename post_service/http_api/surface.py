"""HTTP endpoints: zone info + surface extraction for VTK.js frontend."""
import json
import vtk
from fastapi import Response, Query


def setup(app, engine):
    @app.get("/api/zones/{session_id}")
    async def get_zones(session_id: str, file: str = Query(None)):
        """Return live zone/scalar info from current session (reflects post-calculation changes)."""
        state = engine.session_mgr.get(session_id)
        if state is None:
            return Response(content=b"[]", media_type="application/json", status_code=404)
        post_data = state.get_post_data(file)
        if post_data is None:
            return Response(content=b"[]", media_type="application/json", status_code=404)
        summary = post_data.get_summary()
        # Inject frame info from FrameSequence
        seq = state.get_sequence(file)
        if seq:
            summary["frame_count"] = seq.frame_count
            summary["time_labels"] = seq.time_labels
            summary["max_cache"] = seq._max_cache
            # Global scalar ranges across all frames (from preload cache if ready)
            if seq.frame_count > 1 and seq._global_ranges is not None:
                summary["scalar_ranges"] = seq._global_ranges
            elif seq.frame_count > 1:
                # Preload not done yet — trigger it and skip ranges for now
                seq.start_preload()
        return Response(
            content=json.dumps(summary, ensure_ascii=False).encode(),
            media_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    @app.put("/api/frame_cache/{session_id}")
    async def set_frame_cache(session_id: str, max_cache: int = Query(50), file: str = Query(None)):
        """Set the max frame cache size for a file's FrameSequence."""
        state = engine.session_mgr.get(session_id)
        if state is None:
            return Response(content=b'{"error":"session not found"}', media_type="application/json", status_code=404)
        seq = state.get_sequence(file)
        if seq is None:
            return Response(content=b'{"error":"no sequence"}', media_type="application/json", status_code=404)
        seq.set_max_cache(max_cache)
        return Response(
            content=json.dumps({"max_cache": seq._max_cache}).encode(),
            media_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    @app.get("/api/surface/{session_id}/{zone}")
    async def get_surface(session_id: str, zone: str, file: str = Query(None), frame: int = Query(0)):
        state = engine.session_mgr.get(session_id)
        if state is None:
            return Response(content=b"", status_code=404)
        post_data = state.get_post_data(file, frame=frame if frame > 0 else None)
        if post_data is None:
            return Response(content=b"", status_code=404)

        try:
            # Check VTP surface cache first (avoids re-running GeometryFilter + XMLWriter)
            file_key = file or state._active_file or ""
            cached = state.get_cached_surface(file_key, zone, frame)
            if cached is not None:
                return Response(
                    content=cached,
                    media_type="application/vnd.vtk.vtp",
                    headers={"Access-Control-Allow-Origin": "*"},
                )

            # Find zone block by name in the multiblock dataset
            multiblock = post_data.get_vtk_data()

            if zone == "__all__":
                # Merge all zones into a single polydata
                appender = vtk.vtkAppendPolyData()
                for i in range(multiblock.GetNumberOfBlocks()):
                    block = multiblock.GetBlock(i)
                    if block is None:
                        continue
                    geo = vtk.vtkGeometryFilter()
                    geo.SetInputData(block)
                    geo.Update()
                    appender.AddInputData(geo.GetOutput())
                appender.Update()
                polydata = appender.GetOutput()
            else:
                target = None
                for i in range(multiblock.GetNumberOfBlocks()):
                    meta = multiblock.GetMetaData(i)
                    if meta and meta.Get(vtk.vtkCompositeDataSet.NAME()) == zone:
                        target = multiblock.GetBlock(i)
                        break
                if target is None:
                    return Response(content=b"", status_code=404)

                # Extract surface (handles both surface and volume meshes)
                geo = vtk.vtkGeometryFilter()
                geo.SetInputData(target)
                geo.Update()
                polydata = geo.GetOutput()

            # Write to in-memory VTP (XML PolyData, binary + zlib — fastest on the wire)
            writer = vtk.vtkXMLPolyDataWriter()
            writer.SetDataModeToBinary()
            writer.SetCompressorTypeToZLib()
            writer.WriteToOutputStringOn()
            writer.SetInputData(polydata)
            writer.Write()
            vtp_bytes = writer.GetOutputString()
            if isinstance(vtp_bytes, str):
                vtp_bytes = vtp_bytes.encode("latin-1")

            # Cache VTP bytes for future requests
            state.put_cached_surface(file_key, zone, frame, vtp_bytes)

            return Response(
                content=vtp_bytes,
                media_type="application/vnd.vtk.vtp",
                headers={"Access-Control-Allow-Origin": "*"},
            )
        except Exception as e:
            return Response(content=f"Error: {e}".encode(), status_code=500)
