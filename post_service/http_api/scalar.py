"""HTTP API: GET /api/scalar/{session_id}/{zone}/{name} — return scalar data as raw bytes."""

from fastapi import Response, Query


def setup(app, engine):
    @app.get("/api/scalar/{session_id}/{zone}/{name}")
    async def get_scalar(session_id: str, zone: str, name: str, file: str = Query(None)):
        state = engine.session_mgr.get(session_id)
        if state is None:
            return Response(status_code=404)
        post_data = state.get_post_data(file)
        if post_data is None:
            return Response(status_code=404)
        try:
            data = post_data.get_scalar(zone, name).tobytes()
        except ValueError:
            return Response(status_code=404)
        return Response(content=data, media_type="application/octet-stream")
