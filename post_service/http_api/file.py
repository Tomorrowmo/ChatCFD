"""HTTP API: GET /api/file/{path} — serve a file from disk."""

import os

from fastapi import Response
from fastapi.responses import FileResponse


def setup(app, engine):
    @app.get("/api/file/{path:path}")
    async def get_file(path: str):
        normalized = os.path.normpath(path).replace("\\", "/")
        if not os.path.isfile(normalized):
            return Response(status_code=404)
        return FileResponse(normalized)
