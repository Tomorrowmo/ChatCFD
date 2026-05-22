"""HTTP API: GET /api/samples — list built-in sample CFD cases.

Lets the frontend offer "try with sample data" buttons. The server resolves
absolute paths (it knows its own install location); the frontend never needs
to guess where the bundled cases live.
"""

import os

# Code root (chatcfd/) — two levels up from this file (post_service/http_api/).
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Built-in sample cases, ordered smallest-first (best for a quick first try).
_SAMPLES = [
    {
        "id": "ysy",
        "label": "翼型算例 ysy",
        "desc": "小型 CGNS 算例，含压力/速度场，加载快，适合快速体验",
        "rel_path": "tests/data/ysy/ysy.cgns",
    },
    {
        "id": "x37b",
        "label": "X-37B 飞行器",
        "desc": "大型 CGNS 算例（~480MB），首次加载较慢",
        "rel_path": "tests/data/X37b/x37b-02.cgns",
    },
]


def setup(app, engine):
    @app.get("/api/samples")
    async def list_samples():
        """Return built-in sample cases that actually exist on disk."""
        result = []
        for s in _SAMPLES:
            abs_path = os.path.normpath(
                os.path.join(_REPO_ROOT, s["rel_path"])
            ).replace("\\", "/")
            if not os.path.isfile(abs_path):
                continue
            size_mb = round(os.path.getsize(abs_path) / (1024 * 1024), 1)
            result.append({
                "id": s["id"],
                "label": s["label"],
                "desc": s["desc"],
                "path": abs_path,
                "size_mb": size_mb,
            })
        return {"samples": result}
