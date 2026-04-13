<script setup>
import { ref, watch, computed, onMounted, onBeforeUnmount } from 'vue'
import TimeControls from './TimeControls.vue'

import '@kitware/vtk.js/Rendering/Profiles/Geometry'
import '@kitware/vtk.js/Rendering/Profiles/Glyph'
import vtkFullScreenRenderWindow from '@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow'
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor'
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper'
import vtkGlyph3DMapper from '@kitware/vtk.js/Rendering/Core/Glyph3DMapper'
import vtkArrowSource from '@kitware/vtk.js/Filters/Sources/ArrowSource'
import vtkDataArray from '@kitware/vtk.js/Common/Core/DataArray'
import vtkXMLPolyDataReader from '@kitware/vtk.js/IO/XML/XMLPolyDataReader'
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction'
import vtkScalarBarActor from '@kitware/vtk.js/Rendering/Core/ScalarBarActor'
import vtkAxesActor from '@kitware/vtk.js/Rendering/Core/AxesActor'
import vtkOrientationMarkerWidget from '@kitware/vtk.js/Interaction/Widgets/OrientationMarkerWidget'

const props = defineProps({
  path: { type: String, required: true },
  sessionId: { type: String, default: '' },
  baseZone: { type: String, default: '' },  // wall/tri zone name → load as background model
  sourceFile: { type: String, default: '' }, // source file path for multi-file sessions
  frameFiles: { type: Array, default: () => [] },  // output_files_by_frame
  frameCount: { type: Number, default: 1 },
  timeLabels: { type: Array, default: () => [] },
})

const containerRef = ref(null)
const statusMsg = ref('')
const scalarNames = ref([])
const selectedScalar = ref('')
const vectorNames = ref([])          // [{name, loc, maxMagnitude}] for 3-component arrays
const selectedVector = ref('')
const displayMode = ref('scalar')    // 'scalar' | 'vector'
const arrowScale = ref(1.0)
const opacity = ref(1.0)
const selectedPreset = ref('jet')
const currentFrame = ref(0)
const globalScalarRanges = ref({})  // {scalarName: [min, max]} across all frames

// The actual path to load — switches with frame for multi-frame results
const activePath = computed(() => {
  if (props.frameCount > 1 && props.frameFiles.length > currentFrame.value) {
    return props.frameFiles[currentFrame.value]
  }
  return props.path
})

const colorPresets = {
  jet:         [[0,0,0,1], [0.25,0,1,1], [0.5,0,1,0], [0.75,1,1,0], [1,1,0,0]],
  coolwarm:    [[0,0.231,0.298,0.753], [0.5,0.865,0.865,0.865], [1,0.706,0.016,0.150]],
  rainbow:     [[0,0.278,0,0.714], [0.25,0,0,1], [0.5,0,1,0], [0.75,1,1,0], [1,1,0,0]],
  viridis:     [[0,0.267,0.004,0.329], [0.25,0.282,0.141,0.457], [0.5,0.127,0.566,0.550], [0.75,0.544,0.774,0.247], [1,0.993,0.906,0.144]],
  grayscale:   [[0,0,0,0], [1,1,1,1]],
  blueRed:     [[0,0,0,1], [1,1,0,0]],
}

const timeControlsRef = ref(null)

let fullScreenRenderer = null
let loadedPolydata = null
let currentActor = null
let baseModelPolydata = null
let hasLoadedOnce = false
let glyphMapper = null   // persistent for arrow scale updates without full rebuild

onMounted(() => {
  initViewer()
  addOrientationAxes()
  loadVtp()
  // Precompute global scalar ranges across all frame files for consistent coloring
  if (props.frameFiles.length > 1) precomputeGlobalRanges()
})

onBeforeUnmount(() => {
  if (fullScreenRenderer) {
    fullScreenRenderer.delete()
    fullScreenRenderer = null
  }
})

watch(activePath, () => { loadVtp() })
watch(selectedScalar, () => { if (loadedPolydata && displayMode.value === 'scalar') renderPolydata() })
watch(selectedPreset, () => { if (loadedPolydata) render() })
watch(opacity, (val) => {
  if (currentActor) {
    currentActor.getProperty().setOpacity(val)
    fullScreenRenderer?.getRenderWindow()?.render()
  }
})
watch(displayMode, () => { if (loadedPolydata) render() })
watch(selectedVector, () => { if (loadedPolydata && displayMode.value === 'vector') renderVectorField() })
watch(arrowScale, (val) => {
  // Fast path: only update scale factor without rebuilding the scene
  if (glyphMapper && displayMode.value === 'vector') {
    const v = vectorNames.value.find(x => x.name === selectedVector.value)
    glyphMapper.setScaleFactor(computeAutoScale(v?.maxMagnitude || 1) * val)
    fullScreenRenderer?.getRenderWindow()?.render()
  }
})

function initViewer() {
  if (!containerRef.value) return
  fullScreenRenderer = vtkFullScreenRenderWindow.newInstance({
    rootContainer: containerRef.value,
    containerStyle: { width: '100%', height: '100%' },
    background: [0.92, 0.93, 0.95],
  })
  // Prevent browser auto-scroll on middle mouse so VTK.js pan works
  containerRef.value.addEventListener('mousedown', (e) => {
    if (e.button === 1) e.preventDefault()
  })
}

function addOrientationAxes() {
  if (!fullScreenRenderer) return
  try {
    const axes = vtkAxesActor.newInstance()
    const widget = vtkOrientationMarkerWidget.newInstance({
      actor: axes,
      interactor: fullScreenRenderer.getRenderWindow().getInteractor(),
    })
    widget.setEnabled(true)
    widget.setViewportCorner(vtkOrientationMarkerWidget.Corners.BOTTOM_LEFT)
    widget.setViewportSize(0.15)
    widget.setMinPixelSize(80)
    widget.setMaxPixelSize(200)
  } catch (err) {
    console.warn('[VtpBrowser] Could not add orientation axes:', err.message)
  }
}

async function precomputeGlobalRanges() {
  /** Load all frame files in background, collect min/max for each scalar + vector magnitude. */
  const ranges = {}
  function mergeRange(name, lo, hi) {
    if (name in ranges) {
      ranges[name][0] = Math.min(ranges[name][0], lo)
      ranges[name][1] = Math.max(ranges[name][1], hi)
    } else {
      ranges[name] = [lo, hi]
    }
  }
  for (const filePath of props.frameFiles) {
    try {
      const safePath = filePath.split('/').map(s => encodeURIComponent(s)).join('/')
      const resp = await fetch(`http://localhost:8000/api/file/${safePath}`)
      if (!resp.ok) continue
      const buffer = await resp.arrayBuffer()
      const reader = vtkXMLPolyDataReader.newInstance()
      reader.parseAsArrayBuffer(buffer)
      const polydata = reader.getOutputData(0)
      const pointData = polydata.getPointData()
      const cellData = polydata.getCellData()

      // 1-component scalars
      for (const dataObj of [pointData, cellData]) {
        for (let i = 0; i < dataObj.getNumberOfArrays(); i++) {
          const arr = dataObj.getArrayByIndex(i)
          if (arr.getNumberOfComponents() !== 1) continue
          const [lo, hi] = arr.getRange()
          mergeRange(arr.getName(), lo, hi)
        }
      }

      // 3-component point vectors → compute magnitude range
      for (let i = 0; i < pointData.getNumberOfArrays(); i++) {
        const arr = pointData.getArrayByIndex(i)
        if (arr.getNumberOfComponents() !== 3) continue
        const data = arr.getData()
        const n = arr.getNumberOfTuples()
        let lo = Infinity, hi = -Infinity
        for (let j = 0; j < n; j++) {
          const k = j * 3
          const mag = Math.sqrt(data[k] ** 2 + data[k + 1] ** 2 + data[k + 2] ** 2)
          if (mag < lo) lo = mag
          if (mag > hi) hi = mag
        }
        if (lo <= hi) mergeRange(arr.getName() + '_Magnitude', lo, hi)
      }

      // Component triplets (_x/_y/_z) → synthesize magnitude range
      const pt1C = []
      for (let i = 0; i < pointData.getNumberOfArrays(); i++) {
        const a = pointData.getArrayByIndex(i)
        if (a.getNumberOfComponents() === 1) pt1C.push(a.getName())
      }
      const seen = new Set()
      for (const [sx, sy, sz] of [['_x', '_y', '_z'], ['X', 'Y', 'Z']]) {
        for (const name of pt1C) {
          if (!name.endsWith(sx)) continue
          const base = name.slice(0, -sx.length)
          if (!pt1C.includes(base + sy) || !pt1C.includes(base + sz)) continue
          const vecName = base || 'Velocity'
          if (seen.has(vecName)) continue
          seen.add(vecName)
          const dX = pointData.getArrayByName(name).getData()
          const dY = pointData.getArrayByName(base + sy).getData()
          const dZ = pointData.getArrayByName(base + sz).getData()
          const n = dX.length
          let lo = Infinity, hi = -Infinity
          for (let j = 0; j < n; j++) {
            const mag = Math.sqrt(dX[j] ** 2 + dY[j] ** 2 + dZ[j] ** 2)
            if (mag < lo) lo = mag
            if (mag > hi) hi = mag
          }
          if (lo <= hi) mergeRange(vecName + '_Magnitude', lo, hi)
        }
      }
    } catch { /* skip failed frames */ }
  }
  globalScalarRanges.value = ranges
  console.log('[VtpBrowser] Global scalar ranges:', ranges)
}

async function loadBaseModel() {
  if (!props.sessionId || !props.baseZone) return
  try {
    const fileParam = props.sourceFile ? `?file=${encodeURIComponent(props.sourceFile)}` : ''
    const url = `http://localhost:8000/api/surface/${props.sessionId}/${encodeURIComponent(props.baseZone)}${fileParam}`
    const resp = await fetch(url)
    if (!resp.ok) return
    const buffer = await resp.arrayBuffer()
    const reader = vtkXMLPolyDataReader.newInstance()
    reader.parseAsArrayBuffer(buffer)
    baseModelPolydata = reader.getOutputData(0)
  } catch (err) {
    console.warn('[VtpBrowser] Failed to load base model:', err.message)
  }
}

async function loadVtp() {
  if (!fullScreenRenderer || !activePath.value) return
  statusMsg.value = 'Loading...'

  try {
    // Load base model and result in parallel
    const safePath = activePath.value.split('/').map(s => encodeURIComponent(s)).join('/')
    const url = `http://localhost:8000/api/file/${safePath}`

    const [resp] = await Promise.all([
      fetch(url),
      loadBaseModel(),
    ])

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const buffer = await resp.arrayBuffer()

    const reader = vtkXMLPolyDataReader.newInstance()
    reader.parseAsArrayBuffer(buffer)
    loadedPolydata = reader.getOutputData(0)

    // Collect scalar (1-comp) and vector (3-comp) arrays
    const sNames = []
    const vNames = []
    const pd = loadedPolydata.getPointData()
    const cd = loadedPolydata.getCellData()
    for (let i = 0; i < pd.getNumberOfArrays(); i++) {
      const a = pd.getArrayByIndex(i)
      const nc = a.getNumberOfComponents()
      const name = a.getName()
      if (nc === 1 && !name.endsWith('_Magnitude')) sNames.push({ name, loc: 'point' })
      else if (nc === 3) vNames.push({ name, loc: 'point' })
    }
    for (let i = 0; i < cd.getNumberOfArrays(); i++) {
      const a = cd.getArrayByIndex(i)
      const nc = a.getNumberOfComponents()
      const name = a.getName()
      if (nc === 1 && !name.endsWith('_Magnitude')) sNames.push({ name, loc: 'cell' })
      // cell-data vectors not supported by Glyph3DMapper in vtk.js — skip
    }

    // Synthesize vectors from component triplets (e.g., velocity_x/y/z → velocity)
    const pointScalar1C = sNames.filter(s => s.loc === 'point').map(s => s.name)
    const tripletSuffixes = [['_x', '_y', '_z'], ['X', 'Y', 'Z']]
    for (const [sx, sy, sz] of tripletSuffixes) {
      for (const name of pointScalar1C) {
        if (!name.endsWith(sx)) continue
        const base = name.slice(0, -sx.length)
        const nameY = base + sy
        const nameZ = base + sz
        if (!pointScalar1C.includes(nameY) || !pointScalar1C.includes(nameZ)) continue
        const vecName = base || 'Velocity'
        if (vNames.some(v => v.name === vecName)) continue

        const arrX = pd.getArrayByName(name)
        const arrY = pd.getArrayByName(nameY)
        const arrZ = pd.getArrayByName(nameZ)
        const nTuples = arrX.getNumberOfTuples()
        const vecData = new Float32Array(nTuples * 3)
        const magData = new Float32Array(nTuples)
        let maxMag = 0
        for (let j = 0; j < nTuples; j++) {
          const vx = arrX.getData()[j]
          const vy = arrY.getData()[j]
          const vz = arrZ.getData()[j]
          vecData[j * 3] = vx
          vecData[j * 3 + 1] = vy
          vecData[j * 3 + 2] = vz
          const mag = Math.sqrt(vx * vx + vy * vy + vz * vz)
          magData[j] = mag
          if (mag > maxMag) maxMag = mag
        }
        pd.addArray(vtkDataArray.newInstance({
          name: vecName, values: vecData, numberOfComponents: 3,
        }))
        const magName = vecName + '_Magnitude'
        pd.addArray(vtkDataArray.newInstance({ name: magName, values: magData }))
        vNames.push({ name: vecName, loc: 'point', maxMagnitude: maxMag })
      }
    }

    // Pre-compute magnitude scalar for each point-data vector (for glyph coloring)
    for (const v of vNames) {
      const vecArr = pd.getArrayByName(v.name)
      const data = vecArr.getData()
      const nTuples = vecArr.getNumberOfTuples()
      const magData = new Float32Array(nTuples)
      let maxMag = 0
      for (let j = 0; j < nTuples; j++) {
        const idx = j * 3
        const mag = Math.sqrt(data[idx] ** 2 + data[idx + 1] ** 2 + data[idx + 2] ** 2)
        magData[j] = mag
        if (mag > maxMag) maxMag = mag
      }
      v.maxMagnitude = maxMag
      // Add magnitude as a scalar array on point data (for Glyph3DMapper coloring)
      const magName = v.name + '_Magnitude'
      if (!pd.getArrayByName(magName)) {
        pd.addArray(vtkDataArray.newInstance({ name: magName, values: magData }))
      }
    }

    sNames.sort((a, b) => a.name.localeCompare(b.name))
    scalarNames.value = sNames
    vectorNames.value = vNames
    if (sNames.length && !selectedScalar.value) {
      const preferred = sNames.find(s => s.name === 'VelocityMagnitude')
      selectedScalar.value = preferred ? preferred.name : sNames[0].name
    }
    if (vNames.length && !selectedVector.value) {
      selectedVector.value = vNames[0].name
    }

    render()
  } catch (err) {
    statusMsg.value = `Failed: ${err.message}`
    console.error('VtpBrowser error:', err)
    timeControlsRef.value?.frameReady()  // don't hang playback on error
  }
}

function renderPolydata() {
  if (!fullScreenRenderer || !loadedPolydata) return
  const renderer = fullScreenRenderer.getRenderer()
  const renderWindow = fullScreenRenderer.getRenderWindow()
  renderer.removeAllViewProps()

  // Add base model (body surface) as light gray background
  if (baseModelPolydata) {
    const baseMapper = vtkMapper.newInstance()
    baseMapper.setInputData(baseModelPolydata)
    baseMapper.setScalarVisibility(false)
    const baseActor = vtkActor.newInstance()
    baseActor.setMapper(baseMapper)
    baseActor.getProperty().setColor(0.82, 0.84, 0.86)
    baseActor.getProperty().setOpacity(0.6)
    renderer.addActor(baseActor)
  }

  const mapper = vtkMapper.newInstance()
  mapper.setInputData(loadedPolydata)

  const scalarInfo = scalarNames.value.find(s => s.name === selectedScalar.value)
  if (scalarInfo) {
    const pd = loadedPolydata.getPointData()
    const cd = loadedPolydata.getCellData()
    const useCellData = scalarInfo.loc === 'cell'
    const arr = useCellData ? cd.getArrayByName(scalarInfo.name) : pd.getArrayByName(scalarInfo.name)

    if (arr) {
      const perFrame = arr.getRange()
      // Use global range (consistent across all frames) if available, else per-frame
      const globalR = globalScalarRanges.value[scalarInfo.name]
      const [lo, hi] = globalR || perFrame
      const ctf = vtkColorTransferFunction.newInstance()
      const preset = colorPresets[selectedPreset.value] || colorPresets.jet
      for (const [t, r, g, b] of preset) {
        ctf.addRGBPoint(lo + t * (hi - lo), r, g, b)
      }

      if (useCellData) {
        cd.setActiveScalars(scalarInfo.name)
        mapper.setScalarModeToUseCellData()
      } else {
        pd.setActiveScalars(scalarInfo.name)
        mapper.setScalarModeToUsePointData()
      }
      mapper.setLookupTable(ctf)
      mapper.setUseLookupTableScalarRange(false)
      mapper.setScalarRange(lo, hi)
      mapper.setScalarVisibility(true)
      mapper.setColorByArrayName(scalarInfo.name)

      const bar = vtkScalarBarActor.newInstance()
      bar.setScalarsToColors(ctf)
      bar.setAxisLabel(scalarInfo.name)
      renderer.addActor(bar)
    }
  }

  const actor = vtkActor.newInstance()
  actor.setMapper(mapper)
  actor.getProperty().setOpacity(opacity.value)
  if (!scalarInfo) {
    actor.getProperty().setColor(0.5, 0.7, 0.9)
  }
  // Reduce lighting influence so scalar colors are more consistent across view angles
  actor.getProperty().setAmbient(0.6)
  actor.getProperty().setDiffuse(0.4)
  actor.getProperty().setSpecular(0.0)
  currentActor = actor
  renderer.addActor(actor)
  if (!hasLoadedOnce) {
    renderer.resetCamera()
    hasLoadedOnce = true
  } else {
    // Keep user's camera position but update near/far clip planes for new geometry bounds
    renderer.resetCameraClippingRange()
  }
  renderWindow.render()
  statusMsg.value = ''
  timeControlsRef.value?.frameReady()
}

function computeAutoScale(maxMagnitude) {
  if (!loadedPolydata) return 1
  const b = loadedPolydata.getBounds()
  const diag = Math.sqrt((b[1] - b[0]) ** 2 + (b[3] - b[2]) ** 2 + (b[5] - b[4]) ** 2)
  return maxMagnitude > 0 ? 0.02 * diag / maxMagnitude : 0.02 * diag
}

function renderVectorField() {
  if (!fullScreenRenderer || !loadedPolydata) return
  const renderer = fullScreenRenderer.getRenderer()
  const renderWindow = fullScreenRenderer.getRenderWindow()
  renderer.removeAllViewProps()
  glyphMapper = null

  const vectorInfo = vectorNames.value.find(x => x.name === selectedVector.value)
  if (!vectorInfo) return

  // 1. Base surface (translucent gray geometry context)
  const baseData = baseModelPolydata || loadedPolydata
  const baseMapper = vtkMapper.newInstance()
  baseMapper.setInputData(baseData)
  baseMapper.setScalarVisibility(false)
  const baseActor = vtkActor.newInstance()
  baseActor.setMapper(baseMapper)
  baseActor.getProperty().setColor(0.82, 0.84, 0.86)
  baseActor.getProperty().setOpacity(0.5)
  baseActor.getProperty().setBackfaceCulling(true)
  renderer.addActor(baseActor)

  // 2. Arrow source
  const arrow = vtkArrowSource.newInstance({
    tipResolution: 6, tipRadius: 0.1, tipLength: 0.35,
    shaftResolution: 6, shaftRadius: 0.03,
  })

  // 3. Glyph3DMapper
  glyphMapper = vtkGlyph3DMapper.newInstance()
  glyphMapper.setInputData(loadedPolydata, 0)
  glyphMapper.setInputConnection(arrow.getOutputPort(), 1)
  glyphMapper.setOrientationArray(selectedVector.value)
  glyphMapper.setOrientationMode(vtkGlyph3DMapper.OrientationModes.DIRECTION)
  glyphMapper.setScaleMode(vtkGlyph3DMapper.ScaleModes.SCALE_BY_MAGNITUDE)
  glyphMapper.setScaleArray(selectedVector.value)
  glyphMapper.setScaleFactor(computeAutoScale(vectorInfo.maxMagnitude) * arrowScale.value)

  // 4. Color by pre-computed magnitude scalar
  const magName = selectedVector.value + '_Magnitude'
  const magArr = loadedPolydata.getPointData().getArrayByName(magName)
  if (magArr) {
    const perFrame = magArr.getRange()
    const globalR = globalScalarRanges.value[magName]
    let [lo, hi] = globalR || perFrame
    if (lo >= hi) hi = lo + 1  // guard degenerate range
    const ctf = vtkColorTransferFunction.newInstance()
    const preset = colorPresets[selectedPreset.value] || colorPresets.jet
    for (const [t, r, g, b] of preset) {
      ctf.addRGBPoint(lo + t * (hi - lo), r, g, b)
    }
    glyphMapper.setLookupTable(ctf)
    glyphMapper.setScalarRange(lo, hi)
    glyphMapper.setScalarVisibility(true)
    glyphMapper.setColorByArrayName(magName)
    glyphMapper.setScalarModeToUsePointFieldData()

    const bar = vtkScalarBarActor.newInstance()
    bar.setScalarsToColors(ctf)
    bar.setAxisLabel(selectedVector.value + ' Magnitude')
    renderer.addActor(bar)
  }

  // 5. Actor
  const actor = vtkActor.newInstance()
  actor.setMapper(glyphMapper)
  actor.getProperty().setAmbient(0.5)
  actor.getProperty().setDiffuse(0.5)
  currentActor = actor
  renderer.addActor(actor)

  if (!hasLoadedOnce) {
    renderer.resetCamera()
    hasLoadedOnce = true
  } else {
    renderer.resetCameraClippingRange()
  }
  renderWindow.render()
  statusMsg.value = ''
  timeControlsRef.value?.frameReady()
}

function render() {
  if (displayMode.value === 'vector' && selectedVector.value) {
    renderVectorField()
  } else {
    renderPolydata()
  }
}
</script>

<template>
  <div class="vtp-browser">
    <div class="controls" v-if="scalarNames.length || vectorNames.length">
      <label v-if="vectorNames.length">
        Display:
        <select v-model="displayMode">
          <option value="scalar">Scalar</option>
          <option value="vector">Vector (Arrows)</option>
        </select>
      </label>
      <template v-if="displayMode === 'scalar'">
        <label>
          Scalar:
          <select v-model="selectedScalar">
            <option value="">None (geometry)</option>
            <option v-for="s in scalarNames" :key="s.name" :value="s.name">
              {{ s.name }}
            </option>
          </select>
        </label>
      </template>
      <template v-if="displayMode === 'vector'">
        <label>
          Vector:
          <select v-model="selectedVector">
            <option v-for="v in vectorNames" :key="v.name" :value="v.name">
              {{ v.name }}
            </option>
          </select>
        </label>
        <label class="opacity-label">
          Scale:
          <input type="range" v-model.number="arrowScale" min="0.1" max="5" step="0.1" class="opacity-slider" />
          <span class="opacity-value">{{ arrowScale.toFixed(1) }}x</span>
        </label>
      </template>
      <label>
        Color:
        <select v-model="selectedPreset">
          <option value="jet">Jet</option>
          <option value="coolwarm">Cool-Warm</option>
          <option value="rainbow">Rainbow</option>
          <option value="viridis">Viridis</option>
          <option value="blueRed">Blue-Red</option>
          <option value="grayscale">Grayscale</option>
        </select>
      </label>
      <label v-if="displayMode === 'scalar'" class="opacity-label">
        Opacity:
        <input type="range" v-model.number="opacity" min="0" max="1" step="0.05" class="opacity-slider" />
        <span class="opacity-value">{{ Math.round(opacity * 100) }}%</span>
      </label>
    </div>
    <TimeControls
      v-if="frameCount > 1"
      ref="timeControlsRef"
      :frameCount="frameCount"
      :timeLabels="timeLabels"
      v-model="currentFrame"
    />
    <div class="viewer-container" ref="containerRef">
      <div v-if="statusMsg" class="viewer-overlay">{{ statusMsg }}</div>
      <div class="viewer-hints">
        <span class="hint-item">Drag: Rotate</span>
        <span class="hint-sep">|</span>
        <span class="hint-item">Shift+Drag: Pan</span>
        <span class="hint-sep">|</span>
        <span class="hint-item">Scroll: Zoom</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.vtp-browser {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 8px;
  min-height: 0;
}
.controls {
  display: flex;
  gap: 12px;
  padding: 8px 12px;
  background: var(--bg-tertiary);
  border-radius: 6px;
  flex-shrink: 0;
}
.controls label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}
.controls select {
  background: var(--bg-input, var(--bg-secondary));
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 12px;
}
.opacity-label {
  white-space: nowrap;
}
.opacity-slider {
  width: 80px;
  vertical-align: middle;
  accent-color: var(--accent);
}
.opacity-value {
  display: inline-block;
  width: 32px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.viewer-container {
  position: relative;
  width: 100%;
  flex: 1;
  min-height: 400px;
}
.viewer-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 14px;
  pointer-events: none;
}
.viewer-hints {
  position: absolute;
  top: 8px;
  left: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(6px);
  padding: 4px 10px;
  border-radius: 6px;
  pointer-events: none;
  z-index: 2;
  white-space: nowrap;
}
.hint-item {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.75);
  display: flex;
  align-items: center;
  gap: 4px;
}
.hint-item kbd {
  display: inline-block;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 10px;
  font-family: inherit;
  color: rgba(255, 255, 255, 0.9);
  line-height: 1.4;
}
.hint-sep {
  color: rgba(255, 255, 255, 0.2);
  font-size: 11px;
}
</style>
