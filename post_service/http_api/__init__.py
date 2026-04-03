"""HTTP API thin shells — each module exposes setup(app, engine)."""

from post_service.http_api.mesh import setup as setup_mesh
from post_service.http_api.scalar import setup as setup_scalar
from post_service.http_api.file import setup as setup_file
from post_service.http_api.upload import setup as setup_upload


def setup_all(app, engine):
    """Register all HTTP API routes on the given FastAPI app."""
    setup_mesh(app, engine)
    setup_scalar(app, engine)
    setup_file(app, engine)
    setup_upload(app, engine)
