import os
import vtk

NAME = "render"
DESCRIPTION = "Generate offscreen PNG image(s). Can render a zone or a VTP file. For multi-block VTP (e.g. slices), outputs one PNG per block."
DEFAULTS = {
    "scalar": None,           # scalar name for coloring (None = geometry only)
    "input_file": None,       # VTP file path to render (None = render zone from loaded data)
    "width": 1920,
    "height": 1080,
    "background": [0.2, 0.2, 0.3],
    "camera_position": None,  # [x,y,z] or None for auto-fit
    "camera_direction": None, # "x+"|"x-"|"y+"|"y-"|"z+"|"z-" for axis-aligned view
    "show_colorbar": True,
}


def _render_polydata(polydata, params, output_path):
    """Render a single polydata to PNG. Returns output_path or None on failure."""
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(polydata)

    scalar_name = params.get("scalar")
    if scalar_name:
        arr = polydata.GetPointData().GetArray(scalar_name)
        if arr is None:
            arr = polydata.GetCellData().GetArray(scalar_name)
        if arr:
            if polydata.GetPointData().GetArray(scalar_name):
                mapper.SetScalarModeToUsePointFieldData()
            else:
                mapper.SetScalarModeToCellData()
            mapper.SelectColorArray(scalar_name)
            # Use global scalar range if provided, else per-block range
            scalar_range = params.get("_scalar_range") or arr.GetRange()
            mapper.SetScalarRange(scalar_range)
            mapper.ScalarVisibilityOn()

            lut = vtk.vtkLookupTable()
            lut.SetHueRange(0.667, 0.0)  # blue to red
            lut.SetNumberOfColors(256)
            lut.Build()
            mapper.SetLookupTable(lut)

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)

    bg = params.get("background", [0.2, 0.2, 0.3])
    renderer = vtk.vtkRenderer()
    renderer.AddActor(actor)
    renderer.SetBackground(bg[0], bg[1], bg[2])

    if scalar_name and params.get("show_colorbar", True) and mapper.GetScalarVisibility():
        scalar_bar = vtk.vtkScalarBarActor()
        scalar_bar.SetLookupTable(mapper.GetLookupTable())
        scalar_bar.SetTitle(scalar_name)
        scalar_bar.SetNumberOfLabels(5)
        renderer.AddActor2D(scalar_bar)

    width = int(params.get("width", 1920))
    height = int(params.get("height", 1080))
    render_window = vtk.vtkRenderWindow()
    render_window.SetOffScreenRendering(1)
    render_window.SetSize(width, height)
    render_window.AddRenderer(renderer)

    # Camera
    cam_dir = params.get("camera_direction")
    if cam_dir:
        _set_camera_direction(renderer, cam_dir)
    cam_pos = params.get("camera_position")
    if cam_pos:
        renderer.GetActiveCamera().SetPosition(cam_pos[0], cam_pos[1], cam_pos[2])
    renderer.ResetCamera()

    render_window.Render()

    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(render_window)
    w2i.SetScale(1)
    w2i.SetInputBufferTypeToRGB()
    w2i.ReadFrontBufferOff()
    w2i.Update()

    writer = vtk.vtkPNGWriter()
    writer.SetFileName(output_path)
    writer.SetInputConnection(w2i.GetOutputPort())
    writer.Write()

    render_window.Finalize()
    return output_path


def _set_camera_direction(renderer, direction):
    """Set camera to an axis-aligned view direction."""
    camera = renderer.GetActiveCamera()
    camera.SetFocalPoint(0, 0, 0)
    directions = {
        "x+": ([1, 0, 0], [0, 0, 1]),
        "x-": ([-1, 0, 0], [0, 0, 1]),
        "y+": ([0, 1, 0], [0, 0, 1]),
        "y-": ([0, -1, 0], [0, 0, 1]),
        "z+": ([0, 0, 1], [0, 1, 0]),
        "z-": ([0, 0, -1], [0, 1, 0]),
    }
    pos, up = directions.get(direction, ([0, 0, 1], [0, 1, 0]))
    camera.SetPosition(pos[0], pos[1], pos[2])
    camera.SetViewUp(up[0], up[1], up[2])


def _get_global_scalar_range(reader_output, scalar_name):
    """Compute min/max of a scalar across all blocks in a multiblock dataset."""
    global_min = float("inf")
    global_max = float("-inf")
    n = reader_output.GetNumberOfBlocks() if hasattr(reader_output, "GetNumberOfBlocks") else 0
    for i in range(n):
        block = reader_output.GetBlock(i)
        if block is None:
            continue
        arr = block.GetPointData().GetArray(scalar_name)
        if arr is None:
            arr = block.GetCellData().GetArray(scalar_name)
        if arr:
            lo, hi = arr.GetRange()
            global_min = min(global_min, lo)
            global_max = max(global_max, hi)
    if global_min == float("inf"):
        return None
    return (global_min, global_max)


def execute(post_data, params: dict, zone_name: str, **kwargs) -> dict:
    input_file = params.get("input_file")

    # --- Mode A: render a VTP file (possibly multi-block → multiple PNGs) ---
    if input_file:
        input_file = os.path.normpath(input_file).replace("\\", "/")
        if not os.path.isfile(input_file):
            return {"error": f"Input file not found: {input_file}"}

        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(input_file)
        reader.Update()
        polydata = reader.GetOutput()

        if polydata is None or polydata.GetNumberOfPoints() == 0:
            # Try as multiblock
            mb_reader = vtk.vtkXMLMultiBlockDataReader()
            mb_reader.SetFileName(input_file)
            mb_reader.Update()
            mb = mb_reader.GetOutput()
            if mb and mb.GetNumberOfBlocks() > 0:
                return _render_multiblock(mb, params, input_file, post_data)
            return {"error": f"No renderable data in {input_file}"}

        # Check if single polydata has multiple pieces (e.g. slice output)
        # vtkXMLPolyDataReader loads everything into one polydata.
        # Slice VTP files store multiple planes as separate cells — render as one image.
        render_dir = _make_render_dir(post_data, input_file)
        fname = os.path.splitext(os.path.basename(input_file))[0]
        scalar_name = params.get("scalar")
        scalar_label = scalar_name or "geometry"
        out_path = os.path.normpath(
            os.path.join(render_dir, f"{fname}_{scalar_label}.png")
        ).replace("\\", "/")

        _render_polydata(polydata, params, out_path)

        width = int(params.get("width", 1920))
        height = int(params.get("height", 1080))
        return {
            "type": "file",
            "summary": f"Rendered {fname} with {scalar_label} ({width}x{height}), saved to {out_path}",
            "data": {"output_file": out_path, "width": width, "height": height},
            "output_files": [out_path],
        }

    # --- Mode B: render zone from loaded data (original behavior) ---
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

    geo = vtk.vtkGeometryFilter()
    geo.SetInputData(target)
    geo.Update()
    polydata = geo.GetOutput()

    render_dir = _make_render_dir(post_data)
    zone_label = zone_name or "all"
    scalar_label = params.get("scalar") or "geometry"
    out_path = os.path.normpath(
        os.path.join(render_dir, f"{zone_label}_{scalar_label}.png")
    ).replace("\\", "/")

    _render_polydata(polydata, params, out_path)

    width = int(params.get("width", 1920))
    height = int(params.get("height", 1080))
    return {
        "type": "file",
        "summary": f"Rendered {zone_label} with {scalar_label} coloring ({width}x{height}), saved to {out_path}",
        "data": {"output_file": out_path, "width": width, "height": height, "scalar": params.get("scalar")},
        "output_files": [out_path],
    }


def _render_multiblock(mb, params, input_file, post_data):
    """Render each block in a multiblock dataset as a separate PNG."""
    n = mb.GetNumberOfBlocks()
    render_dir = _make_render_dir(post_data, input_file)
    fname = os.path.splitext(os.path.basename(input_file))[0]
    scalar_name = params.get("scalar")
    scalar_label = scalar_name or "geometry"

    # Compute global scalar range across all blocks for consistent coloring
    if scalar_name:
        global_range = _get_global_scalar_range(mb, scalar_name)
        if global_range:
            params = {**params, "_scalar_range": global_range}

    paths = []
    for i in range(n):
        block = mb.GetBlock(i)
        if block is None or block.GetNumberOfPoints() == 0:
            continue
        # Convert to polydata if needed
        if not isinstance(block, vtk.vtkPolyData):
            geo = vtk.vtkGeometryFilter()
            geo.SetInputData(block)
            geo.Update()
            block = geo.GetOutput()

        out_path = os.path.normpath(
            os.path.join(render_dir, f"{fname}_{scalar_label}_{i:04d}.png")
        ).replace("\\", "/")
        _render_polydata(block, params, out_path)
        paths.append(out_path)

    if not paths:
        return {"error": "No blocks with data to render"}

    width = int(params.get("width", 1920))
    height = int(params.get("height", 1080))
    return {
        "type": "file",
        "summary": f"Rendered {len(paths)} frames from {fname} ({scalar_label}, {width}x{height}). Files: {paths[0]} ... {paths[-1]}",
        "data": {
            "output_file": paths[0],
            "frame_count": len(paths),
            "width": width,
            "height": height,
        },
        "output_files": paths,
    }


def _make_render_dir(post_data, input_file=None):
    """Create and return the Render output directory."""
    if input_file:
        base_dir = os.path.dirname(input_file)
    else:
        file_stem = os.path.splitext(os.path.basename(post_data.file_path))[0]
        base_dir = os.path.join(os.path.dirname(post_data.file_path), file_stem)
    render_dir = os.path.join(base_dir, "Render")
    os.makedirs(render_dir, exist_ok=True)
    return render_dir
