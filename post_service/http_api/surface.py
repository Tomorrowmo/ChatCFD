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
        return Response(
            content=json.dumps(summary, ensure_ascii=False).encode(),
            media_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    @app.get("/api/surface/{session_id}/{zone}")
    async def get_surface(session_id: str, zone: str, file: str = Query(None)):
        state = engine.session_mgr.get(session_id)
        if state is None:
            return Response(content=b"", status_code=404)
        post_data = state.get_post_data(file)
        if post_data is None:
            return Response(content=b"", status_code=404)

        try:
            # Find zone block by name in the multiblock dataset
            multiblock = post_data.get_vtk_data()
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

            return Response(
                content=vtp_bytes,
                media_type="application/vnd.vtk.vtp",
                headers={"Access-Control-Allow-Origin": "*"},
            )
        except Exception as e:
            return Response(content=f"Error: {e}".encode(), status_code=500)
