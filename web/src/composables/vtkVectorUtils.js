// VTK.js helpers for vector-field detection and arrow-scale computation.
// Shared by VtkViewer (single-actor mode) and SceneViewer (multi-layer mode)
// so both stay in sync on how synthesized vectors / magnitudes are produced.

import vtkDataArray from '@kitware/vtk.js/Common/Core/DataArray'
import vtkPolyData from '@kitware/vtk.js/Common/DataModel/PolyData'
import vtkPoints from '@kitware/vtk.js/Common/Core/Points'

// Scan polydata: classify 1-comp scalars vs 3-comp vectors, synthesize
// vectors from <base>_x/_y/_z and <base>X/Y/Z scalar triplets, compute a
// magnitude array for each vector. Mutates polydata (adds synthesized
// arrays). Returns {scalars, vectors, vectorsInfo, scalarsLoc}.
export function inspectAndSynthesize(polydata) {
  const pd = polydata.getPointData()
  const cd = polydata.getCellData()
  const sNames = []  // [{name, loc}]
  const vNames = []  // [{name, loc, maxMagnitude}]

  for (let i = 0; i < pd.getNumberOfArrays(); i++) {
    const a = pd.getArrayByIndex(i)
    if (!a) continue
    const name = a.getName()
    if (!name || name === 'Scalars_') continue
    const nc = a.getNumberOfComponents ? a.getNumberOfComponents() : 1
    if (nc === 1 && !name.endsWith('_Magnitude')) sNames.push({ name, loc: 'point' })
    else if (nc === 3) vNames.push({ name, loc: 'point', maxMagnitude: 0 })
  }
  for (let i = 0; i < cd.getNumberOfArrays(); i++) {
    const a = cd.getArrayByIndex(i)
    if (!a) continue
    const name = a.getName()
    if (!name) continue
    const nc = a.getNumberOfComponents ? a.getNumberOfComponents() : 1
    if (nc === 1 && !name.endsWith('_Magnitude')) sNames.push({ name, loc: 'cell' })
  }

  // Synthesize vectors from <base>_x/_y/_z and <base>X/Y/Z scalar triplets
  const pointScalars = sNames.filter(s => s.loc === 'point').map(s => s.name)
  const synthesized = new Set()
  for (const suf of [['_x','_y','_z'], ['X','Y','Z']]) {
    const [sx, sy, sz] = suf
    for (const name of pointScalars) {
      if (!name.endsWith(sx)) continue
      const base = name.slice(0, -sx.length)
      if (pointScalars.indexOf(base + sy) < 0 || pointScalars.indexOf(base + sz) < 0) continue
      const vecName = base || 'Velocity'
      if (synthesized.has(vecName)) continue
      if (vNames.find(v => v.name === vecName)) continue
      const arrX = pd.getArrayByName(name)
      const arrY = pd.getArrayByName(base + sy)
      const arrZ = pd.getArrayByName(base + sz)
      if (!arrX || !arrY || !arrZ) continue
      const nT = arrX.getNumberOfTuples()
      const dX = arrX.getData(), dY = arrY.getData(), dZ = arrZ.getData()
      const vecData = new Float32Array(nT * 3)
      const magData = new Float32Array(nT)
      let maxMag = 0
      for (let k = 0; k < nT; k++) {
        const vx = dX[k], vy = dY[k], vz = dZ[k]
        vecData[k * 3] = vx; vecData[k * 3 + 1] = vy; vecData[k * 3 + 2] = vz
        const m = Math.sqrt(vx * vx + vy * vy + vz * vz)
        magData[k] = m
        if (m > maxMag) maxMag = m
      }
      pd.addArray(vtkDataArray.newInstance({ name: vecName, values: vecData, numberOfComponents: 3 }))
      pd.addArray(vtkDataArray.newInstance({ name: vecName + '_Magnitude', values: magData }))
      vNames.push({ name: vecName, loc: 'point', maxMagnitude: maxMag })
      synthesized.add(vecName)
    }
  }

  // Compute magnitude for each native (non-synthesized) 3-component vector
  for (const v of vNames) {
    if (v.maxMagnitude > 0) continue
    const arr = pd.getArrayByName(v.name)
    if (!arr) continue
    const data = arr.getData()
    const nT = arr.getNumberOfTuples()
    const magData = new Float32Array(nT)
    let maxMag = 0
    for (let i = 0; i < nT; i++) {
      const k = i * 3
      const m = Math.sqrt(data[k] * data[k] + data[k + 1] * data[k + 1] + data[k + 2] * data[k + 2])
      magData[i] = m
      if (m > maxMag) maxMag = m
    }
    v.maxMagnitude = maxMag
    const magName = v.name + '_Magnitude'
    if (!pd.getArrayByName(magName)) {
      pd.addArray(vtkDataArray.newInstance({ name: magName, values: magData }))
    }
  }

  sNames.sort((a, b) => a.name.localeCompare(b.name))
  vNames.sort((a, b) => a.name.localeCompare(b.name))

  return {
    scalars: sNames.map(s => s.name),
    vectors: vNames.map(v => v.name),
    scalarsLoc: sNames,
    vectorsInfo: vNames,
  }
}

// Auto arrow scale: normalize so the longest arrow is ~2% of bbox diagonal.
export function computeAutoScale(polydata, maxMag) {
  const b = polydata.getBounds()
  const diag = Math.sqrt(
    (b[1] - b[0]) ** 2 + (b[3] - b[2]) ** 2 + (b[5] - b[4]) ** 2
  )
  return maxMag > 0 ? 0.02 * diag / maxMag : 0.02 * diag
}

// Subsample point set for glyphing. A glyph per point on a 100k-point zone
// freezes the browser, so when the point count exceeds maxArrows we keep
// every Nth point (uniform stride) and build a lightweight vtkPolyData that
// carries only the vector + magnitude arrays the glyph mapper needs.
//
// Returns {polydata, sampled, count, stride}. When no subsampling is needed
// the input polydata is returned unchanged (sampled=false).
export function subsampleForGlyphs(polydata, vectorName, maxArrows = 5000) {
  const pd = polydata.getPointData()
  const vecArr = pd.getArrayByName(vectorName)
  const points = polydata.getPoints()
  if (!vecArr || !points) {
    return { polydata, sampled: false, count: 0, stride: 1 }
  }

  const nPts = points.getNumberOfPoints()
  if (nPts <= maxArrows) {
    return { polydata, sampled: false, count: nPts, stride: 1 }
  }

  const stride = Math.ceil(nPts / maxArrows)
  const ptsData = points.getData()
  const vecData = vecArr.getData()
  const magArr = pd.getArrayByName(vectorName + '_Magnitude')
  const magData = magArr ? magArr.getData() : null

  const sampledCount = Math.floor((nPts - 1) / stride) + 1
  const newPts = new Float32Array(sampledCount * 3)
  const newVec = new Float32Array(sampledCount * 3)
  const newMag = magData ? new Float32Array(sampledCount) : null

  let j = 0
  for (let i = 0; i < nPts; i += stride) {
    newPts[j * 3] = ptsData[i * 3]
    newPts[j * 3 + 1] = ptsData[i * 3 + 1]
    newPts[j * 3 + 2] = ptsData[i * 3 + 2]
    newVec[j * 3] = vecData[i * 3]
    newVec[j * 3 + 1] = vecData[i * 3 + 1]
    newVec[j * 3 + 2] = vecData[i * 3 + 2]
    if (newMag) newMag[j] = magData[i]
    j++
  }

  const out = vtkPolyData.newInstance()
  const outPoints = vtkPoints.newInstance()
  outPoints.setData(newPts, 3)
  out.setPoints(outPoints)
  out.getPointData().addArray(vtkDataArray.newInstance({
    name: vectorName, values: newVec, numberOfComponents: 3,
  }))
  if (newMag) {
    out.getPointData().addArray(vtkDataArray.newInstance({
      name: vectorName + '_Magnitude', values: newMag,
    }))
  }

  return { polydata: out, sampled: true, count: j, stride }
}
