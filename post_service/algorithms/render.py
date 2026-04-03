import os
import vtk

NAME = "render"
DESCRIPTION = "Generate an offscreen rendering (PNG image) of mesh with scalar coloring."
DEFAULTS = {
    "scalar": None,           # scalar name for coloring (None = geometry only)
    "width": 1920,
    "height": 1080,
    "background": [0.2, 0.2, 0.3],  # dark background
    "camera_position": None,  # [x,y,z] or None for auto-fit
    "show_colorbar": True,
}


def execute(post_data, params: dict, zone_name: str) -> dict:
    multiblock = post_data.get_vtk_data()

    # Get target data
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

    # Convert to surface for rendering
    geo = vtk.vtkGeometryFilter()
    geo.SetInputData(target)
    geo.Update()
    polydata = geo.GetOutput()

    # Mapper
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
            mapper.SetScalarRange(arr.GetRange())
            mapper.ScalarVisibilityOn()

            # Color lookup table
            lut = vtk.vtkLookupTable()
            lut.SetHueRange(0.667, 0.0)  # blue to red
            lut.SetNumberOfColors(256)
            lut.Build()
            mapper.SetLookupTable(lut)

    # Actor
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)

    # Renderer
    bg = params.get("background", [0.2, 0.2, 0.3])
    renderer = vtk.vtkRenderer()
    renderer.AddActor(actor)
    renderer.SetBackground(bg[0], bg[1], bg[2])

    # Color bar
    if scalar_name and params.get("show_colorbar", True) and mapper.GetScalarVisibility():
        scalar_bar = vtk.vtkScalarBarActor()
        scalar_bar.SetLookupTable(mapper.GetLookupTable())
        scalar_bar.SetTitle(scalar_name)
        scalar_bar.SetNumberOfLabels(5)
        renderer.AddActor2D(scalar_bar)

    # Render window (offscreen)
    width = int(params.get("width", 1920))
    height = int(params.get("height", 1080))
    render_window = vtk.vtkRenderWindow()
    render_window.SetOffScreenRendering(1)
    render_window.SetSize(width, height)
    render_window.AddRenderer(renderer)

    # Camera
    cam_pos = params.get("camera_position")
    if cam_pos:
        renderer.GetActiveCamera().SetPosition(cam_pos[0], cam_pos[1], cam_pos[2])
    renderer.ResetCamera()

    render_window.Render()

    # Capture to image
    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(render_window)
    w2i.SetScale(1)
    w2i.SetInputBufferTypeToRGB()
    w2i.ReadFrontBufferOff()
    w2i.Update()

    # Save PNG
    output_dir = os.path.dirname(post_data.file_path)
    render_dir = os.path.join(output_dir, "Render")
    os.makedirs(render_dir, exist_ok=True)

    zone_label = zone_name or "all"
    scalar_label = scalar_name or "geometry"
    output_path = os.path.join(render_dir, f"{zone_label}_{scalar_label}.png")
    output_path = os.path.normpath(output_path).replace("\\", "/")

    writer = vtk.vtkPNGWriter()
    writer.SetFileName(output_path)
    writer.SetInputConnection(w2i.GetOutputPort())
    writer.Write()

    # Cleanup
    render_window.Finalize()

    return {
        "type": "file",
        "summary": f"Rendered {zone_label} with {scalar_label} coloring ({width}x{height}), saved to {output_path}",
        "data": {
            "output_file": output_path,
            "width": width,
            "height": height,
            "scalar": scalar_name,
        },
        "output_files": [output_path],
    }
