"""HTTP API: GET /api/geometry/{session_id}/{result_id} — return geometry result as VTP bytes."""

import vtk
from fastapi import Response


def setup(app, engine):
    @app.get("/api/geometry/{session_id}/{result_id}")
    async def get_geometry(session_id: str, result_id: str):
        state = engine.session_mgr.get(session_id)
        if state is None:
            return Response(status_code=404)
        vtk_data = state.geometry_results.get(result_id)
        if vtk_data is None:
            return Response(status_code=404)

        # Try PolyData writer first, fall back to UnstructuredGrid
        if isinstance(vtk_data, vtk.vtkPolyData):
            writer = vtk.vtkXMLPolyDataWriter()
        else:
            writer = vtk.vtkXMLUnstructuredGridWriter()

        writer.SetInputData(vtk_data)
        writer.WriteToOutputStringOn()
        writer.Write()
        content = writer.GetOutputString()

        return Response(
            content=content,
            media_type="application/xml",
            headers={"Content-Disposition": f"inline; filename={result_id}.vtp"},
        )
