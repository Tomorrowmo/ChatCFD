"""HTTP API: GET /api/scalar/{session_id}/{zone}/{name} — return scalar data as raw bytes."""

from fastapi import Response


def setup(app, engine):
    @app.get("/api/scalar/{session_id}/{zone}/{name}")
    async def get_scalar(session_id: str, zone: str, name: str):
        data = engine.get_scalar_data(session_id, zone, name)
        if data is None:
            return Response(status_code=404)
        return Response(content=data, media_type="application/octet-stream")
