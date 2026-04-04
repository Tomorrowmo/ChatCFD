"""Compare scalar statistics between two zones in the loaded file."""

import numpy as np

NAME = "compare"
DESCRIPTION = "Compare scalar statistics between two zones in the loaded file."
DEFAULTS = {
    "scalar": None,   # required: scalar name to compare
    "zone_a": None,   # required: first zone name
    "zone_b": None,   # required: second zone name
}


def execute(post_data, params: dict, zone_name: str) -> dict:
    scalar = params.get("scalar")
    zone_a = params.get("zone_a")
    zone_b = params.get("zone_b")

    if not scalar:
        return {"error": "Parameter 'scalar' is required."}
    if not zone_a or not zone_b:
        return {"error": "Parameters 'zone_a' and 'zone_b' are required."}

    try:
        arr_a = post_data.get_scalar(zone_a, scalar)
    except ValueError as e:
        return {"error": str(e)}
    try:
        arr_b = post_data.get_scalar(zone_b, scalar)
    except ValueError as e:
        return {"error": str(e)}

    def _stats(arr):
        return {
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "count": int(len(arr)),
        }

    stats_a = _stats(arr_a)
    stats_b = _stats(arr_b)

    mean_diff = stats_a["mean"] - stats_b["mean"]
    # Percentage of max difference relative to the larger absolute mean
    ref = max(abs(stats_a["mean"]), abs(stats_b["mean"]))
    mean_diff_percent = (mean_diff / ref * 100.0) if ref > 0 else 0.0
    max_diff = stats_a["max"] - stats_b["max"]
    min_diff = stats_a["min"] - stats_b["min"]

    diff = {
        "mean_diff": float(mean_diff),
        "mean_diff_percent": float(mean_diff_percent),
        "max_diff": float(max_diff),
        "min_diff": float(min_diff),
    }

    summary = (
        f"Compared '{scalar}' between '{zone_a}' and '{zone_b}': "
        f"mean_diff={mean_diff:.4g} ({mean_diff_percent:+.2f}%), "
        f"max_diff={max_diff:.4g}, min_diff={min_diff:.4g}"
    )

    return {
        "type": "comparison",
        "summary": summary,
        "data": {
            "scalar": scalar,
            "zone_a": {"zone": zone_a, **stats_a},
            "zone_b": {"zone": zone_b, **stats_b},
            "diff": diff,
        },
        "output_files": [],
    }
