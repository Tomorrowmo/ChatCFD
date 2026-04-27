import numpy as np

NAME = "statistics"
DESCRIPTION = """计算 zone 内标量的 min/max/mean/std 统计。任意 zone。
scalars 不传 → 全部标量；传列表 → 仅统计指定标量。
输出：data 字段包含每个标量的 {min, max, mean, std}；summary 只给摘要。
适用：快速浏览物理量范围、找极值、定位异常。"""
DEFAULTS = {
    "scalars": None,  # None = all scalars in zone
}


def execute(post_data, params: dict, zone_name: str, **kwargs) -> dict:
    scalars = params.get("scalars")
    if not scalars:
        scalars = post_data.get_scalar_names(zone_name)

    data = {}
    for name in scalars:
        try:
            arr = post_data.get_scalar(zone_name, name)
        except ValueError:
            continue
        data[name] = {
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
        }

    n = len(data)
    if n == 0:
        summary = f"{zone_name}: 无可统计标量"
    else:
        preview_names = list(data.keys())[:2]
        preview = "; ".join(
            f"{name}[min={data[name]['min']:.4g}, max={data[name]['max']:.4g}, "
            f"mean={data[name]['mean']:.4g}]"
            for name in preview_names
        )
        if n <= 2:
            summary = f"{zone_name}: {preview}"
        else:
            summary = f"{zone_name}: {n} 个标量。示例 → {preview}；其余见 data.*"

    return {
        "type": "numerical",
        "summary": summary,
        "data": data,
        "output_files": [],
    }
