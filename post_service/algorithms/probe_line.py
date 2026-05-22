"""Sample scalar values along a line and generate distribution plot."""

import os
import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

NAME = "probe_line"
DESCRIPTION = """沿一条直线采样标量值，生成分布曲线图（PNG）+ 数据（CSV）。
point1/point2: 线的起止坐标 [x,y,z]，不传则自动取 zone bbox 对角线。
scalar: 采样的标量名。resolution: 采样点数（默认 200）。
适用：Cp 沿弦长分布、压力沿展向变化、温度沿流向梯度。"""
DEFAULTS = {
    "scalar": None,
    "point1": None,
    "point2": None,
    "resolution": 200,
    "axis_label": None,
    "output_images": True,
}


def execute(post_data, params: dict, zone_name: str, **kwargs) -> dict:
    scalar_name = params.get("scalar")
    if not scalar_name:
        return {"error": "Parameter 'scalar' is required."}

    zones = post_data.get_zones()
    ref_zone = zone_name if zone_name and zone_name in zones else zones[0]
    ref_block = post_data._get_block(ref_zone)

    try:
        resolved = post_data._resolve_name(ref_zone, scalar_name, ref_block)
    except ValueError as e:
        return {"error": str(e)}

    multiblock = post_data.get_vtk_data()
    if zone_name:
        target = None
        for i in range(multiblock.GetNumberOfBlocks()):
            meta = multiblock.GetMetaData(i)
            if meta and meta.Get(vtk.vtkCompositeDataSet.NAME()) == zone_name:
                target = multiblock.GetBlock(i)
                break
        if target is None:
            return {"error": f"Zone '{zone_name}' not found"}
    else:
        append = vtk.vtkAppendFilter()
        for i in range(multiblock.GetNumberOfBlocks()):
            block = multiblock.GetBlock(i)
            if block:
                append.AddInputData(block)
        append.Update()
        target = append.GetOutput()

    if target.GetPointData().GetArray(resolved) is None and \
       target.GetCellData().GetArray(resolved) is not None:
        c2p = vtk.vtkCellDataToPointData()
        c2p.SetInputData(target)
        c2p.Update()
        target = c2p.GetOutput()

    bounds = target.GetBounds()
    p1 = params.get("point1") or [bounds[0], bounds[2], bounds[4]]
    p2 = params.get("point2") or [bounds[1], bounds[3], bounds[5]]
    resolution = int(params.get("resolution", 200))

    line = vtk.vtkLineSource()
    line.SetPoint1(*[float(v) for v in p1])
    line.SetPoint2(*[float(v) for v in p2])
    line.SetResolution(resolution)
    line.Update()

    probe = vtk.vtkProbeFilter()
    probe.SetInputConnection(line.GetOutputPort())
    probe.SetSourceData(target)
    probe.Update()
    probed = probe.GetOutput()

    arr = probed.GetPointData().GetArray(resolved)
    if arr is None:
        return {"error": f"Probe returned no data for '{scalar_name}'. Check point1/point2 are inside the mesh."}

    values = vtk_to_numpy(arr)
    coords = vtk_to_numpy(probed.GetPoints().GetData())
    diffs = np.diff(coords, axis=0, prepend=coords[:1])
    distances = np.cumsum(np.sqrt(np.sum(diffs**2, axis=1)))

    valid = probed.GetPointData().GetArray("vtkValidPointMask")
    if valid is not None:
        mask = vtk_to_numpy(valid).astype(bool)
        distances = distances[mask]
        values = values[mask]
        coords = coords[mask]

    if len(values) == 0:
        return {"error": "Probe line is entirely outside the mesh. Adjust point1/point2."}

    output_dir = kwargs.get("output_dir") or os.path.join(
        os.path.dirname(post_data.file_path),
        os.path.splitext(os.path.basename(post_data.file_path))[0],
    )
    plot_dir = os.path.join(output_dir, "Plot")
    os.makedirs(plot_dir, exist_ok=True)

    zone_label = zone_name or "all"
    base_name = f"{zone_label}_{scalar_name}_line"

    csv_path = os.path.normpath(os.path.join(plot_dir, f"{base_name}.csv")).replace("\\", "/")
    import csv
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["distance", "x", "y", "z", scalar_name])
        for i in range(len(values)):
            w.writerow([float(distances[i]), float(coords[i][0]), float(coords[i][1]), float(coords[i][2]), float(values[i])])

    output_files = [csv_path]
    chart_path = None

    if params.get("output_images", True):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(distances, values, "b-", linewidth=1.5)
        ax.set_xlabel(params.get("axis_label") or "Distance")
        ax.set_ylabel(scalar_name)
        ax.set_title(f"{scalar_name} along line ({zone_label})")
        ax.grid(True, alpha=0.3)

        i_min, i_max = int(np.argmin(values)), int(np.argmax(values))
        ax.annotate(f"min={values[i_min]:.4g}", xy=(distances[i_min], values[i_min]),
                    fontsize=8, color="blue")
        ax.annotate(f"max={values[i_max]:.4g}", xy=(distances[i_max], values[i_max]),
                    fontsize=8, color="red")

        fig.tight_layout()
        chart_path = os.path.normpath(os.path.join(plot_dir, f"{base_name}.png")).replace("\\", "/")
        fig.savefig(chart_path, dpi=150)
        plt.close(fig)
        output_files.append(chart_path)

    return {
        "type": "file",
        "summary": (
            f"Probed {scalar_name} along line from {p1} to {p2}: "
            f"{len(values)} points, range [{float(np.min(values)):.4g}, {float(np.max(values)):.4g}]. "
            f"CSV: {csv_path}" + (f" Chart: {chart_path}" if chart_path else "")
        ),
        "data": {
            "csv_file": csv_path,
            "chart_file": chart_path,
            "scalar": scalar_name,
            "point1": list(p1),
            "point2": list(p2),
            "n_points": len(values),
            "value_range": [float(np.min(values)), float(np.max(values))],
        },
        "output_files": output_files,
    }
