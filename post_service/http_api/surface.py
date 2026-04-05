"""HTTP endpoint: extract zone surface as VTP binary for VTK.js frontend."""
import vtk
from fastapi import Response


def setup(app, engine):
    @app.get("/api/surface/{session_id}/{zone}")
    async def get_surface(session_id: str, zone: str):
        state = engine.session_mgr.get(session_id)
        if state is None or state.post_data is None:
            return Response(content=b"", status_code=404)

        try:
            # Find zone block by name in the multiblock dataset
            multiblock = state.post_data.get_vtk_data()
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

            # Write to in-memory VTP (XML PolyData, binary + zlib)
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
