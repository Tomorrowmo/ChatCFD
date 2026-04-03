"""HTTP API: POST /api/upload — save uploaded file to a temp directory."""

import os
import tempfile

from fastapi import UploadFile


def setup(app, engine):
    @app.post("/api/upload")
    async def upload_file(file: UploadFile):
        tmp_dir = tempfile.mkdtemp(prefix="chatcfd_")
        dest = os.path.join(tmp_dir, file.filename)
        dest = os.path.normpath(dest).replace("\\", "/")
        content = await file.read()
        with open(dest, "wb") as f:
            f.write(content)
        return {"file_path": dest, "size": len(content)}
