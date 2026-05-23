"""HTTP API: GET /api/samples — list built-in sample CFD cases.

Each sample carries a per-case `analysis_prompt`. The frontend's "完整分析"
button concatenates it after the load command, so the agent gets a
case-specific recipe instead of guessing parameters.

Path resolution: `abs_path` wins if present (for cases living outside the
repo); otherwise `rel_path` is resolved against the repo root. Samples
whose file is missing on disk are silently skipped from the response.
"""

import os

# Code root (chatcfd/) — two levels up from this file (post_service/http_api/).
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

_SAMPLES = [
    {
        "id": "ysy",
        "label": "ysy 升力体航天器",
        "desc": "升力体航天器外流（CGNS），已含 Cp / Mach / Pressure / Velocity / Temperature 标量",
        "rel_path": "tests/data/ysy/ysy.cgns",
        "kind": "external_flow_liftingbody",
        "analysis_prompt": "对这个升力体航天器算例做完整气动分析",
    },
    {
        "id": "x37b",
        "label": "X-37B 飞行器",
        "desc": "高超声速飞行器外流（~480MB CGNS），首次加载较慢。激波、Mach、气动力",
        "rel_path": "tests/data/X37b/x37b-02.cgns",
        "kind": "external_flow_hypersonic",
        "analysis_prompt": "对这个高超声速飞行器算例做完整气动分析",
    },
    {
        "id": "aeroheating",
        "label": "再入飞行器气动加热",
        "desc": "再入飞行器壁面热流（~9MB Tecplot），t=142s。仅表面网格，含 qw/pe/hre",
        "abs_path": "D:/XField/data/fromyu/lire/heat/heat/aeroheating_142.0s.dat",
        "kind": "aeroheating_surface",
        "analysis_prompt": "对这个再入气动加热算例做完整热环境分析",
    },
]


def _resolve_path(sample):
    """Return absolute disk path for a sample entry; abs_path wins over rel_path."""
    if "abs_path" in sample:
        return os.path.normpath(sample["abs_path"]).replace("\\", "/")
    return os.path.normpath(
        os.path.join(_REPO_ROOT, sample["rel_path"])
    ).replace("\\", "/")


def setup(app, engine):
    @app.get("/api/samples")
    async def list_samples():
        """Return built-in sample cases that actually exist on disk."""
        result = []
        for s in _SAMPLES:
            abs_path = _resolve_path(s)
            if not os.path.isfile(abs_path):
                continue
            size_mb = round(os.path.getsize(abs_path) / (1024 * 1024), 1)
            result.append({
                "id": s["id"],
                "label": s["label"],
                "desc": s["desc"],
                "path": abs_path,
                "size_mb": size_mb,
                "kind": s.get("kind", ""),
                "analysis_prompt": s.get("analysis_prompt", ""),
            })
        return {"samples": result}
