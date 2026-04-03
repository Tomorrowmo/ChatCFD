"""Force & moment integration using VTK C++ ForceMomentIntegtal filter."""

import vtk

NAME = "force_moment"
DESCRIPTION = "Integrate pressure/shear forces and moments on surface zones."
DEFAULTS = {
    "pressure": "pressure",
    "density": None,       # required for coefficients
    "velocity": None,      # required for coefficients
    "refArea": None,       # required for coefficients
    "refLength": 1.0,
    "flip_normals": True,
    "alpha_angle": 0.0,
    "beta_angle": 0.0,
    "reference_point": [0.0, 0.0, 0.0],
    "shear_force": None,   # e.g. ["shear_x", "shear_y", "shear_z"]
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_zone_block(multiblock: vtk.vtkMultiBlockDataSet, zone_name: str):
    """Find a block by zone name in multiblock metadata. Returns vtkDataSet or None."""
    n = multiblock.GetNumberOfBlocks()
    for i in range(n):
        block = multiblock.GetBlock(i)
        if block is None:
            continue
        meta = multiblock.GetMetaData(i)
        if meta is not None and meta.Has(vtk.vtkCompositeDataSet.NAME()):
            name = meta.Get(vtk.vtkCompositeDataSet.NAME())
            if name == zone_name:
                return block
    return None


def _merge_all_blocks(multiblock: vtk.vtkMultiBlockDataSet):
    """Merge all blocks into a single unstructured grid via vtkAppendFilter."""
    append_filter = vtk.vtkAppendFilter()
    n = multiblock.GetNumberOfBlocks()
    for i in range(n):
        block = multiblock.GetBlock(i)
        if block is not None:
            append_filter.AddInputData(block)
    append_filter.Update()
    return append_filter.GetOutput()


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

def execute(post_data, params: dict, zone_name: str) -> dict:
    multiblock = post_data.get_vtk_data()

    # Select zone or merge all
    if zone_name:
        point_set = _get_zone_block(multiblock, zone_name)
        if point_set is None:
            return {"error": f"Zone '{zone_name}' not found in multiblock data."}
    else:
        point_set = _merge_all_blocks(multiblock)

    # Build VTK filter
    fmi = vtk.ForceMomentIntegtal()
    fmi.SetInputData(point_set)
    fmi.SetPressureName(params.get("pressure", "pressure"))
    fmi.SetFlipNormals(params.get("flip_normals", True))

    # Reference conditions
    density = params.get("density")
    velocity = params.get("velocity")
    ref_area = params.get("refArea")
    ref_length = params.get("refLength", 1.0)
    has_coefficients = all(v is not None for v in (density, velocity, ref_area))

    fmi.SetReferenceCondition(
        density if density is not None else 1.0,
        velocity if velocity is not None else 1.0,
        ref_area if ref_area is not None else 1.0,
        ref_length,
    )

    # Reference point
    ref_pt = params.get("reference_point", [0.0, 0.0, 0.0])
    fmi.SetReferencePoint(ref_pt[0], ref_pt[1], ref_pt[2])

    # Angles (alpha = angle of attack, beta = sideslip)
    fmi.SetAngles(
        params.get("alpha_angle", 0.0),
        params.get("beta_angle", 0.0),
    )

    # Shear force components (optional)
    shear = params.get("shear_force")
    if shear and len(shear) == 3:
        fmi.SetShearForce(shear[0], shear[1], shear[2])

    # Note: legacy API uses "Updata" (typo preserved from C++ module)
    fmi.Updata()

    # Collect results
    force = {
        "x": fmi.GetTotalForceX(),
        "y": fmi.GetTotalForceY(),
        "z": fmi.GetTotalForceZ(),
    }
    moment = {
        "x": fmi.GetTotalMomentX(),
        "y": fmi.GetTotalMomentY(),
        "z": fmi.GetTotalMomentZ(),
    }

    data = {"force": force, "moment": moment}

    summary_parts = [
        f"Force=({force['x']:.4g}, {force['y']:.4g}, {force['z']:.4g})",
        f"Moment=({moment['x']:.4g}, {moment['y']:.4g}, {moment['z']:.4g})",
    ]

    if has_coefficients:
        coefficients = {
            "lift": fmi.GetLiftCoefficient(),
            "drag": fmi.GetDragCoefficient(),
            "side_force": fmi.GetSideForceCoefficient(),
            "pitch_moment": fmi.GetPitchingMomentCoefficient(),
            "yaw_moment": fmi.GetYawingMomentCoefficient(),
            "roll_moment": fmi.GetRollingMomentCoefficient(),
        }
        data["coefficients"] = coefficients
        summary_parts.append(
            f"CL={coefficients['lift']:.4g}, CD={coefficients['drag']:.4g}"
        )

    target = zone_name if zone_name else "all zones (merged)"
    summary = f"Force/moment on {target}: " + ", ".join(summary_parts)

    return {
        "type": "numerical",
        "summary": summary,
        "data": data,
        "output_files": [],
    }
