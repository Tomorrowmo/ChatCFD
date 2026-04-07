"""HTTP API: file serving + open-in-explorer."""

import os
import subprocess
import sys

from fastapi import Response
from fastapi.responses import FileResponse
from pydantic import BaseModel


class OpenFolderRequest(BaseModel):
    path: str


def setup(app, engine):
    @app.get("/api/file/{path:path}")
    async def get_file(path: str):
        normalized = os.path.normpath(path).replace("\\", "/")
        if not os.path.isfile(normalized):
            return Response(status_code=404)
        return FileResponse(normalized)

    @app.post("/api/open-folder")
    async def open_folder(req: OpenFolderRequest):
        """Open the file's parent folder in system file explorer, selecting the file."""
        normalized = os.path.normpath(req.path)
        if not os.path.exists(normalized):
            return {"error": f"Path not found: {req.path}"}

        try:
            if sys.platform == "win32":
                if os.path.isfile(normalized):
                    # Select the file in Explorer
                    subprocess.Popen(["explorer", "/select,", normalized])
                else:
                    # Open the directory
                    subprocess.Popen(["explorer", normalized])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", normalized])
            else:
                # Linux: open parent directory
                parent = os.path.dirname(normalized) if os.path.isfile(normalized) else normalized
                subprocess.Popen(["xdg-open", parent])
            return {"status": "ok", "path": normalized}
        except Exception as e:
            return {"error": f"Failed to open: {e}"}
