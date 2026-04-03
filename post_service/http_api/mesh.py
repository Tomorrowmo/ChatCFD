"""HTTP API: GET /api/mesh/{session_id}/{zone} — return mesh geometry as raw bytes."""

from fastapi import Response


def setup(app, engine):
    @app.get("/api/mesh/{session_id}/{zone}")
    async def get_mesh(session_id: str, zone: str):
        data = engine.get_mesh_geometry(session_id, zone)
        if data is None:
            return Response(status_code=404)
        return Response(content=data, media_type="application/octet-stream")
