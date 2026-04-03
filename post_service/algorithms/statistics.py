import numpy as np

NAME = "statistics"
DESCRIPTION = "Calculate scalar statistics (min/max/mean/std) for a zone."
DEFAULTS = {
    "scalars": None,  # None = all scalars in zone
}


def execute(post_data, params: dict, zone_name: str) -> dict:
    scalars = params.get("scalars")
    if not scalars:
        scalars = post_data.get_scalar_names(zone_name)

    data = {}
    summaries = []
    for name in scalars:
        try:
            arr = post_data.get_scalar(zone_name, name)
        except ValueError:
            continue
        stats = {
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
        }
        data[name] = stats
        summaries.append(f"{name}: min={stats['min']:.4g}, max={stats['max']:.4g}, mean={stats['mean']:.4g}")

    return {
        "type": "numerical",
        "summary": f"{zone_name} statistics: " + "; ".join(summaries),
        "data": data,
        "output_files": [],
    }
