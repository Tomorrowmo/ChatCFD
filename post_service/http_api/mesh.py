"""HTTP API: GET /api/mesh/{session_id}/{zone} — return mesh geometry as raw bytes."""

from fastapi import Response, Query


def setup(app, engine):
    @app.get("/api/mesh/{session_id}/{zone}")
    async def get_mesh(session_id: str, zone: str, file: str = Query(None)):
        state = engine.session_mgr.get(session_id)
        if state is None:
            return Response(status_code=404)
        post_data = state.get_post_data(file)
        if post_data is None:
            return Response(status_code=404)
        try:
            data = post_data.get_points(zone).tobytes()
        except ValueError:
            return Response(status_code=404)
        return Response(content=data, media_type="application/octet-stream")
