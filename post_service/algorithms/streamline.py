"""Streamline computation using vtkStreamTracer (standard VTK).

Smart seed placement strategy:
1. Compute velocity magnitude on entire domain
2. Find high-velocity region (>= 70th percentile) → these are the "interesting" flow areas
3. Sample seed points from the upstream boundary of this region
4. Result: streamlines automatically cover the key flow features
"""
import os
import math

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

NAME = "streamline"
DESCRIPTION = "Compute streamlines from velocity field with automatic seed placement in key flow regions."
DEFAULTS = {
    "velocity_x": "velocity_x",
    "velocity_y": "velocity_y",
    "velocity_z": "velocity_z",
    "n_seeds": 80,
    "seed_strategy": "auto",          # "auto" | "line" | "plane" | "inlet"
    "seed_start": None,               # [x,y,z] for line seed
    "seed_end": None,                 # [x,y,z] for line seed
    "seed_center": None,              # [x,y,z] for plane seed
    "seed_normal": None,              # [nx,ny,nz] for plane seed
    "seed_radius": None,              # radius for plane seed
    "max_length": None,               # None = auto
    "integration_direction": "forward",
    "tube_radius": None,              # None = auto
    "tube_sides": 12,
}


def _compute_vorticity(data_with_vel):
    """Compute vorticity magnitude using vtkGradientFilter (standard VTK)."""
    gradient = vtk.vtkGradientFilter()
    gradient.SetInputData(data_with_vel)
    gradient.SetInputArrayToProcess(
        0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "Velocity_Vector"
    )
    gradient.ComputeVorticityOn()
    gradient.SetVorticityArrayName("Vorticity")
    gradient.Update()
    output = gradient.GetOutput()
    vort_arr = output.GetPointData().GetArray("Vorticity")
    if vort_arr is None:
        return None
    vorticity = vtk_to_numpy(vort_arr)  # (N, 3)
    return np.linalg.norm(vorticity, axis=1)  # |ω|


def _find_smart_seeds(data_with_vel, n_seeds, bounds, diagonal, multiblock=None):
    """Vorticity-weighted seed placement near the body.

    Based on Feature-based / Derived Field strategy (Sane et al. 2020 survey).
    Key insight: vorticity magnitude = flow feature intensity.
    High vorticity = vortex / separation / shear layer = where streamlines matter.

    3-zone seeding strategy:
      - Zone A (30%): Upstream of body — uniform grid, ensures incoming flow coverage
      - Zone B (50%): Near body — vorticity-weighted, captures flow features
      - Zone C (20%): Wake region — vorticity-weighted, captures trailing vortices
    """
    points = data_with_vel.GetPoints()
    if points is None:
        return None, None

    vel_arr = data_with_vel.GetPointData().GetArray("Velocity_Vector")
    if vel_arr is None:
        return None, None

    coords = vtk_to_numpy(points.GetData())
    velocities = vtk_to_numpy(vel_arr)
    n_pts = len(coords)

    if n_pts == 0:
        return None, None

    vel_mag = np.linalg.norm(velocities, axis=1)
    if vel_mag.max() < 1e-12:
        return None, None

    # Compute vorticity magnitude for weighting
    vort_mag = _compute_vorticity(data_with_vel)
    if vort_mag is None:
        # Fallback to velocity weighting if vorticity computation fails
        vort_mag = vel_mag

    # Find dominant flow direction
    high_vel_mask = vel_mag > np.percentile(vel_mag, 70)
    if high_vel_mask.sum() < 10:
        high_vel_mask = vel_mag > np.percentile(vel_mag, 30)
    mean_vel = velocities[high_vel_mask].mean(axis=0)
    flow_dir = mean_vel / (np.linalg.norm(mean_vel) + 1e-12)

    # Project all points onto flow direction
    projections = coords @ flow_dir

    # Find body
    body_bounds = _find_body_bounds(multiblock)

    if body_bounds is not None:
        bx_min, bx_max, by_min, by_max, bz_min, bz_max = body_bounds
        body_center = np.array([(bx_min+bx_max)/2, (by_min+by_max)/2, (bz_min+bz_max)/2])
        body_diag = math.sqrt(
            (bx_max-bx_min)**2 + (by_max-by_min)**2 + (bz_max-bz_min)**2
        )
        body_proj = body_center @ flow_dir

        # Expanded bounding box for "near body" region
        margin = body_diag * 2.0
        near_body = (
            (coords[:, 0] > bx_min - margin) & (coords[:, 0] < bx_max + margin) &
            (coords[:, 1] > by_min - margin) & (coords[:, 1] < by_max + margin) &
            (coords[:, 2] > bz_min - margin) & (coords[:, 2] < bz_max + margin)
        )

        # Exclude points inside the body
        inner = body_diag * 0.05
        not_inside_body = ~(
            (coords[:, 0] > bx_min + inner) & (coords[:, 0] < bx_max - inner) &
            (coords[:, 1] > by_min + inner) & (coords[:, 1] < by_max - inner) &
            (coords[:, 2] > bz_min + inner) & (coords[:, 2] < bz_max - inner)
        )
        valid = near_body & not_inside_body & (vel_mag > 1e-6)

        # Zone A: upstream (0.5~1.0 body_diag ahead of body front)
        upstream_limit = body_proj - body_diag * 0.3
        upstream_far = body_proj - body_diag * 1.5
        zone_a = valid & (projections < upstream_limit) & (projections > upstream_far)

        # Zone B: near body (from 0.3 body_diag upstream to 0.3 downstream)
        zone_b = valid & (projections >= upstream_limit) & (projections < body_proj + body_diag * 0.5)

        # Zone C: wake (0.3~3.0 body_diag downstream)
        zone_c = valid & (projections >= body_proj + body_diag * 0.3) & (projections < body_proj + body_diag * 3.0)

        # Allocate seeds per zone
        n_a = max(int(n_seeds * 0.3), 5)
        n_b = max(int(n_seeds * 0.5), 5)
        n_c = n_seeds - n_a - n_b

        all_chosen = []

        # Zone A: uniform sampling (incoming flow coverage)
        idx_a = np.where(zone_a)[0]
        if len(idx_a) > 0:
            weights_a = vel_mag[idx_a]
            weights_a = weights_a / (weights_a.sum() + 1e-12)
            pick_a = min(n_a, len(idx_a))
            all_chosen.extend(np.random.choice(idx_a, size=pick_a, replace=False, p=weights_a))

        # Zone B: vorticity-weighted (flow features near body)
        idx_b = np.where(zone_b)[0]
        if len(idx_b) > 0:
            weights_b = vort_mag[idx_b]
            # Add small baseline so low-vorticity areas still get some seeds
            weights_b = weights_b + np.percentile(vort_mag[idx_b], 30)
            weights_b = weights_b / (weights_b.sum() + 1e-12)
            pick_b = min(n_b, len(idx_b))
            all_chosen.extend(np.random.choice(idx_b, size=pick_b, replace=False, p=weights_b))

        # Zone C: vorticity-weighted (wake vortices)
        idx_c = np.where(zone_c)[0]
        if len(idx_c) > 0:
            weights_c = vort_mag[idx_c]
            weights_c = weights_c + np.percentile(vort_mag[idx_c], 20)
            weights_c = weights_c / (weights_c.sum() + 1e-12)
            pick_c = min(n_c, len(idx_c))
            all_chosen.extend(np.random.choice(idx_c, size=pick_c, replace=False, p=weights_c))

        if len(all_chosen) == 0:
            return None, None

        desc = "auto (vorticity-weighted, 3-zone: upstream/body/wake)"
    else:
        # No body found: vorticity-weighted across upstream half
        mid_proj = np.median(projections)
        upstream = projections < mid_proj
        candidate = upstream & (vel_mag > 1e-6)
        idx = np.where(candidate)[0]

        if len(idx) < 5:
            idx = np.where(vel_mag > 1e-6)[0]

        if len(idx) == 0:
            return None, None

        weights = vort_mag[idx] + np.percentile(vort_mag[idx], 30)
        weights = weights / (weights.sum() + 1e-12)
        pick = min(n_seeds, len(idx))
        all_chosen = list(np.random.choice(idx, size=pick, replace=False, p=weights))
        desc = "auto (vorticity-weighted, no body detected)"

    # Build VTK point set from chosen indices
    seed_points = vtk.vtkPoints()
    for idx in all_chosen:
        seed_points.InsertNextPoint(*coords[idx])

    seed_pd = vtk.vtkPolyData()
    seed_pd.SetPoints(seed_points)
    return seed_pd, desc


def _find_body_bounds(multiblock):
    """Try to find the wall/body zone and return its bounding box."""
    if multiblock is None:
        return None
    wall_keywords = ["wall", "body", "wing", "surface", "blade", "airfoil", "hull"]
    n = multiblock.GetNumberOfBlocks()
    for i in range(n):
        meta = multiblock.GetMetaData(i)
        if meta is None:
            continue
        if not meta.Has(vtk.vtkCompositeDataSet.NAME()):
            continue
        name = meta.Get(vtk.vtkCompositeDataSet.NAME()).lower()
        if any(kw in name for kw in wall_keywords):
            block = multiblock.GetBlock(i)
            if block is not None and block.GetNumberOfPoints() > 0:
                return block.GetBounds()
    # If no wall zone found by name, use the smallest zone (likely the body)
    smallest_block = None
    smallest_pts = float('inf')
    for i in range(n):
        block = multiblock.GetBlock(i)
        if block is None:
            continue
        npts = block.GetNumberOfPoints()
        if 0 < npts < smallest_pts:
            smallest_pts = npts
            smallest_block = block
    if smallest_block is not None and smallest_pts < multiblock.GetNumberOfPoints() * 0.5:
        return smallest_block.GetBounds()
    return None


def _get_body_surface(multiblock):
    """Extract body/wall surface as vtkPolyData for combined visualization."""
    if multiblock is None:
        return None
    wall_keywords = ["wall", "body", "wing", "surface", "blade", "airfoil", "hull", "tri"]
    n = multiblock.GetNumberOfBlocks()

    # Find wall zone by name
    for i in range(n):
        meta = multiblock.GetMetaData(i)
        if meta is None:
            continue
        if not meta.Has(vtk.vtkCompositeDataSet.NAME()):
            continue
        name = meta.Get(vtk.vtkCompositeDataSet.NAME()).lower()
        if any(kw in name for kw in wall_keywords):
            block = multiblock.GetBlock(i)
            if block is not None and block.GetNumberOfPoints() > 0:
                # Convert to polydata surface
                geo = vtk.vtkGeometryFilter()
                geo.SetInputData(block)
                geo.Update()
                return geo.GetOutput()

    # Fallback: use smallest zone
    smallest_block = None
    smallest_pts = float('inf')
    for i in range(n):
        block = multiblock.GetBlock(i)
        if block is None:
            continue
        npts = block.GetNumberOfPoints()
        if 0 < npts < smallest_pts:
            smallest_pts = npts
            smallest_block = block
    if smallest_block is not None and smallest_pts < multiblock.GetNumberOfPoints() * 0.5:
        geo = vtk.vtkGeometryFilter()
        geo.SetInputData(smallest_block)
        geo.Update()
        return geo.GetOutput()
    return None


def _find_inlet_boundary_seeds(data_with_vel, n_seeds, bounds):
    """Place seeds on the detected inlet face of the bounding box."""
    points = data_with_vel.GetPoints()
    vel_arr = data_with_vel.GetPointData().GetArray("Velocity_Vector")
    if points is None or vel_arr is None:
        return None

    coords = vtk_to_numpy(points.GetData())
    velocities = vtk_to_numpy(vel_arr)
    vel_mag = np.linalg.norm(velocities, axis=1)

    # Test each of the 6 bounding box faces to find the inlet
    # Inlet = face where average velocity points inward
    dx = bounds[1] - bounds[0]
    dy = bounds[3] - bounds[2]
    dz = bounds[5] - bounds[4]
    tol_frac = 0.05  # 5% thickness for "near face" selection

    faces = [
        ("x-", 0, bounds[0], bounds[0] + dx * tol_frac, np.array([1, 0, 0])),   # xmin face, inward = +x
        ("x+", 0, bounds[1] - dx * tol_frac, bounds[1], np.array([-1, 0, 0])),  # xmax face, inward = -x
        ("y-", 1, bounds[2], bounds[2] + dy * tol_frac, np.array([0, 1, 0])),
        ("y+", 1, bounds[3] - dy * tol_frac, bounds[3], np.array([0, -1, 0])),
        ("z-", 2, bounds[4], bounds[4] + dz * tol_frac, np.array([0, 0, 1])),
        ("z+", 2, bounds[5] - dz * tol_frac, bounds[5], np.array([0, 0, -1])),
    ]

    best_face = None
    best_score = -1

    for name, axis, lo, hi, inward_normal in faces:
        mask = (coords[:, axis] >= lo) & (coords[:, axis] <= hi)
        if mask.sum() < 5:
            continue
        # Score = how much velocity on this face points inward * velocity magnitude
        face_vel = velocities[mask]
        face_mag = vel_mag[mask]
        inward_component = face_vel @ inward_normal
        # Score: average inward flux, weighted by magnitude
        score = (inward_component * face_mag).mean()
        if score > best_score:
            best_score = score
            best_face = (name, mask, axis)

    if best_face is None or best_score <= 0:
        return None

    _, face_mask, _ = best_face
    face_indices = np.where(face_mask)[0]
    face_mags = vel_mag[face_indices]

    # Sample with velocity weighting
    weights = face_mags / (face_mags.sum() + 1e-12)
    n_pick = min(n_seeds, len(face_indices))
    chosen = np.random.choice(face_indices, size=n_pick, replace=False, p=weights)

    seed_points = vtk.vtkPoints()
    for idx in chosen:
        seed_points.InsertNextPoint(*coords[idx])

    seed_pd = vtk.vtkPolyData()
    seed_pd.SetPoints(seed_points)
    return seed_pd


def execute(post_data, params: dict, zone_name: str) -> dict:
    multiblock = post_data.get_vtk_data()

    # Get target block
    if zone_name:
        target = _get_zone_block(multiblock, zone_name)
        if target is None:
            return {"error": f"Zone '{zone_name}' not found"}
    else:
        target = _merge_all_blocks(multiblock)

    # Build velocity vector field from 3 components
    vx_name = str(params.get("velocity_x", "velocity_x"))
    vy_name = str(params.get("velocity_y", "velocity_y"))
    vz_name = str(params.get("velocity_z", "velocity_z"))

    ref_zone = zone_name or post_data.get_zones()[0]
    try:
        post_data.get_scalar(ref_zone, vx_name)
        post_data.get_scalar(ref_zone, vy_name)
        post_data.get_scalar(ref_zone, vz_name)
    except ValueError as e:
        return {"error": f"Velocity field not found: {e}"}

    # If scalars are in cell data, convert to point data first
    # (vtkArrayCalculator and vtkStreamTracer require point data)
    has_point_data = target.GetPointData().GetArray(vx_name) is not None
    if not has_point_data:
        c2p = vtk.vtkCellDataToPointData()
        c2p.SetInputData(target)
        c2p.Update()
        target = c2p.GetOutput()

    # Combine velocity components into vector
    calc = vtk.vtkArrayCalculator()
    calc.SetInputData(target)
    calc.AddScalarArrayName(vx_name)
    calc.AddScalarArrayName(vy_name)
    calc.AddScalarArrayName(vz_name)
    calc.SetFunction(f"{vx_name}*iHat+{vy_name}*jHat+{vz_name}*kHat")
    calc.SetResultArrayName("Velocity_Vector")
    calc.Update()
    data_with_vel = calc.GetOutput()
    data_with_vel.GetPointData().SetActiveVectors("Velocity_Vector")

    # Add velocity magnitude for coloring
    mag_calc = vtk.vtkArrayCalculator()
    mag_calc.SetInputData(data_with_vel)
    mag_calc.AddScalarArrayName(vx_name)
    mag_calc.AddScalarArrayName(vy_name)
    mag_calc.AddScalarArrayName(vz_name)
    mag_calc.SetFunction(f"sqrt({vx_name}^2+{vy_name}^2+{vz_name}^2)")
    mag_calc.SetResultArrayName("VelocityMagnitude")
    mag_calc.Update()
    data_with_vel = mag_calc.GetOutput()
    data_with_vel.GetPointData().SetActiveVectors("Velocity_Vector")

    # Geometry info
    bounds = data_with_vel.GetBounds()
    dx = bounds[1] - bounds[0]
    dy = bounds[3] - bounds[2]
    dz = bounds[5] - bounds[4]
    diagonal = math.sqrt(dx*dx + dy*dy + dz*dz)
    center = [(bounds[0]+bounds[1])/2, (bounds[2]+bounds[3])/2, (bounds[4]+bounds[5])/2]

    n_seeds = int(params.get("n_seeds", 80))
    seed_strategy = str(params.get("seed_strategy", "auto")).lower()
    seed_pd = None
    seed_desc = seed_strategy

    # --- Seed placement ---
    if seed_strategy == "auto":
        # Smart seeding: find body, seed upstream of it
        seed_pd, auto_desc = _find_smart_seeds(data_with_vel, n_seeds, bounds, diagonal, multiblock)
        if seed_pd is not None:
            seed_desc = auto_desc
        else:
            # Fallback to inlet boundary
            seed_pd = _find_inlet_boundary_seeds(data_with_vel, n_seeds, bounds)
            seed_desc = "auto (inlet fallback)"

    elif seed_strategy == "inlet":
        seed_pd = _find_inlet_boundary_seeds(data_with_vel, n_seeds, bounds)
        seed_desc = "inlet boundary"

    elif seed_strategy == "plane":
        seed_center = params.get("seed_center") or center
        seed_normal = params.get("seed_normal") or [1, 0, 0]
        seed_radius = params.get("seed_radius") or diagonal * 0.3
        src = vtk.vtkPointSource()
        src.SetCenter(*seed_center)
        src.SetRadius(seed_radius)
        src.SetNumberOfPoints(n_seeds)
        src.SetDistributionToUniform()
        src.Update()
        seed_pd = src.GetOutput()
        seed_desc = "plane"

    elif seed_strategy == "line":
        seed_start = params.get("seed_start")
        seed_end = params.get("seed_end")
        if seed_start is None:
            seed_start = [center[0], bounds[2] + dy*0.1, center[2]]
        if seed_end is None:
            seed_end = [center[0], bounds[3] - dy*0.1, center[2]]
        src = vtk.vtkLineSource()
        src.SetPoint1(*[float(v) for v in seed_start])
        src.SetPoint2(*[float(v) for v in seed_end])
        src.SetResolution(n_seeds)
        src.Update()
        seed_pd = src.GetOutput()
        seed_desc = "line"

    # Final fallback: line across domain
    if seed_pd is None or seed_pd.GetNumberOfPoints() == 0:
        src = vtk.vtkLineSource()
        src.SetPoint1(bounds[0], center[1], center[2])
        src.SetPoint2(bounds[1], center[1], center[2])
        src.SetResolution(n_seeds)
        src.Update()
        seed_pd = src.GetOutput()
        seed_desc = "fallback (center line)"

    # --- Stream tracer ---
    max_length = params.get("max_length") or diagonal * 2.0

    streamer = vtk.vtkStreamTracer()
    streamer.SetInputData(data_with_vel)
    streamer.SetSourceData(seed_pd)
    streamer.SetMaximumPropagation(float(max_length))

    # Adaptive RK45 integration for smooth lines
    streamer.SetIntegratorTypeToRungeKutta45()
    streamer.SetIntegrationStepUnit(vtk.vtkStreamTracer.LENGTH_UNIT)
    streamer.SetInitialIntegrationStep(diagonal * 0.001)
    streamer.SetMinimumIntegrationStep(diagonal * 0.0001)
    streamer.SetMaximumIntegrationStep(diagonal * 0.01)
    streamer.SetMaximumNumberOfSteps(5000)
    streamer.SetMaximumError(1e-6)

    direction = str(params.get("integration_direction", "forward")).lower()
    if direction == "forward":
        streamer.SetIntegrationDirectionToForward()
    elif direction == "backward":
        streamer.SetIntegrationDirectionToBackward()
    else:
        streamer.SetIntegrationDirectionToBoth()

    streamer.Update()
    raw_output = streamer.GetOutput()

    n_lines = raw_output.GetNumberOfLines() if hasattr(raw_output, 'GetNumberOfLines') else raw_output.GetNumberOfCells()
    n_points = raw_output.GetNumberOfPoints()

    if n_points == 0:
        return {"error": "Streamline produced no data. Try seed_strategy='line' with manual seed_start/seed_end."}

    # --- Tube filter for visibility ---
    # Auto tube radius: use body size if available, otherwise domain diagonal
    body_bounds = _find_body_bounds(multiblock)
    if body_bounds and not params.get("tube_radius"):
        body_diag = math.sqrt(
            (body_bounds[1]-body_bounds[0])**2 +
            (body_bounds[3]-body_bounds[2])**2 +
            (body_bounds[5]-body_bounds[4])**2
        )
        tube_radius = body_diag * 0.003
    else:
        tube_radius = params.get("tube_radius") or diagonal * 0.0005
    tube_sides = int(params.get("tube_sides", 12))

    tube = vtk.vtkTubeFilter()
    tube.SetInputData(raw_output)
    tube.SetRadius(tube_radius)
    tube.SetNumberOfSides(tube_sides)
    tube.SetVaryRadiusToVaryRadiusOff()
    tube.CappingOn()
    tube.Update()
    streamline_poly = tube.GetOutput()

    # --- Combine streamlines + body surface into one output ---
    body_bounds_for_merge = _find_body_bounds(multiblock)
    body_poly = _get_body_surface(multiblock)

    if body_poly is not None:
        # Append body surface + streamline tubes
        appender = vtk.vtkAppendPolyData()
        appender.AddInputData(body_poly)
        appender.AddInputData(streamline_poly)
        appender.Update()
        output = appender.GetOutput()
    else:
        output = streamline_poly

    # Save as VTP
    output_dir = os.path.dirname(post_data.file_path)
    sl_dir = os.path.join(output_dir, "Streamline")
    os.makedirs(sl_dir, exist_ok=True)
    output_path = os.path.normpath(os.path.join(sl_dir, "streamlines.vtp")).replace("\\", "/")

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(output_path)
    writer.SetInputData(output)
    writer.SetDataModeToBinary()
    writer.SetCompressorTypeToZLib()
    writer.Write()

    result_id = f"streamline_{id(output) % 100000:05d}"
    zone_label = zone_name or "all zones"

    return {
        "type": "geometry",
        "summary": (
            f"Streamlines of {zone_label}: {n_lines} lines, {n_points} pts. "
            f"Seed: {seed_desc} ({seed_pd.GetNumberOfPoints()} seeds). "
            f"Color by VelocityMagnitude in 3D viewer. Saved to {output_path}"
        ),
        "data": {
            "result_id": result_id,
            "output_file": output_path,
            "n_lines": n_lines,
            "n_points": n_points,
            "seed_strategy": seed_desc,
        },
        "output_files": [output_path],
        "_vtk_output": output,
    }


def _get_zone_block(multiblock, zone_name):
    for i in range(multiblock.GetNumberOfBlocks()):
        meta = multiblock.GetMetaData(i)
        if meta and meta.Get(vtk.vtkCompositeDataSet.NAME()) == zone_name:
            return multiblock.GetBlock(i)
    return None


def _merge_all_blocks(multiblock):
    append = vtk.vtkAppendFilter()
    for i in range(multiblock.GetNumberOfBlocks()):
        block = multiblock.GetBlock(i)
        if block:
            append.AddInputData(block)
    append.Update()
    return append.GetOutput()
