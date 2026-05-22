<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { POST_SERVICE_URL } from '../config.js'

import '@kitware/vtk.js/Rendering/Profiles/Geometry'
import '@kitware/vtk.js/Rendering/Profiles/Glyph'
import vtkFullScreenRenderWindow from '@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow'
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor'
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper'
import vtkGlyph3DMapper from '@kitware/vtk.js/Rendering/Core/Glyph3DMapper'
import vtkArrowSource from '@kitware/vtk.js/Filters/Sources/ArrowSource'
import vtkXMLPolyDataReader from '@kitware/vtk.js/IO/XML/XMLPolyDataReader'
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction'
import vtkScalarBarActor from '@kitware/vtk.js/Rendering/Core/ScalarBarActor'
import vtkAxesActor from '@kitware/vtk.js/Rendering/Core/AxesActor'
import vtkOrientationMarkerWidget from '@kitware/vtk.js/Interaction/Widgets/OrientationMarkerWidget'
import { inspectAndSynthesize, computeAutoScale, subsampleForGlyphs } from '../composables/vtkVectorUtils.js'

const MAX_ARROWS = 5000  // glyph count cap — above this, points are strided

const props = defineProps({
  sessionId: { type: String, default: 'default' },
  zone: { type: String, default: '' },
  scalarName: { type: String, default: '' },
  path: { type: String, default: '' },
  sourceFile: { type: String, default: '' },
  displayMode: { type: String, default: 'surface' },
  opacity: { type: Number, default: 1.0 },
  colorPreset: { type: String, default: 'jet' },
  frame: { type: Number, default: 0 },
  scalarRange: { type: Array, default: null },  // [min, max] global range across all frames
  renderMode: { type: String, default: 'scalar' },  // 'scalar' | 'vector'
  vectorName: { type: String, default: '' },
  arrowScale: { type: Number, default: 1.0 },
})

const emit = defineEmits(['loaded', 'arrays-detected'])

let hasLoadedOnce = false  // track first load for resetCamera
let loadGeneration = 0     // monotonic counter — stale loadData() calls won't emit 'loaded'

// Vector-mode runtime state: kept so arrowScale prop changes can mutate the
// glyph mapper without re-fetching the VTP. Reset on every loadData() call.
let currentPolydata = null
let currentGlyphMapper = null
let currentVectorMaxMag = null

const colorPresets = {
  jet:         [[0,0,0,1], [0.25,0,1,1], [0.5,0,1,0], [0.75,1,1,0], [1,1,0,0]],
  coolwarm:    [[0,0.231,0.298,0.753], [0.5,0.865,0.865,0.865], [1,0.706,0.016,0.150]],
  rainbow:     [[0,0.278,0,0.714], [0.25,0,0,1], [0.5,0,1,0], [0.75,1,1,0], [1,1,0,0]],
  viridis:     [[0,0.267,0.004,0.329], [0.25,0.282,0.141,0.457], [0.5,0.127,0.566,0.550], [0.75,0.544,0.774,0.247], [1,0.993,0.906,0.144]],
  grayscale:   [[0,0,0,0], [1,1,1,1]],
  blueRed:     [[0,0,0,1], [1,1,0,0]],
}

// inspectAndSynthesize and computeAutoScale moved to composables/vtkVectorUtils.js

const containerRef = ref(null)
const statusMsg = ref('')
const vectorHint = ref('')  // e.g. "已抽稀至 5000 个箭头 (每 12 点取 1)"
let fullScreenRenderer = null

onMounted(() => {
  initViewer()
  addOrientationAxes()
  if (props.path) loadFromFile()
  else if (props.zone) loadData()
  else statusMsg.value = 'Select a zone to view'

  // "R" key to reset camera
  window.addEventListener('keydown', onKeydown)
})

function onKeydown(e) {
  if (e.key === 'r' || e.key === 'R') {
    if (fullScreenRenderer && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
      fullScreenRenderer.getRenderer().resetCamera()
      fullScreenRenderer.getRenderWindow().render()
    }
  }
}

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (fullScreenRenderer) {
    fullScreenRenderer.delete()
    fullScreenRenderer = null
  }
})

watch(
  () => [props.sessionId, props.zone, props.scalarName, props.frame, props.renderMode, props.vectorName],
  () => {
    if (props.zone) loadData()
  }
)

// Arrow scale only affects glyph mapper — no need to re-fetch
watch(
  () => props.arrowScale,
  () => {
    if (currentGlyphMapper && currentVectorMaxMag != null && currentPolydata) {
      currentGlyphMapper.setScaleFactor(
        computeAutoScale(currentPolydata, currentVectorMaxMag) * props.arrowScale
      )
      fullScreenRenderer?.getRenderWindow().render()
    }
  }
)

watch(
  () => props.path,
  (newPath) => {
    if (newPath) loadFromFile()
  }
)

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
    console.warn('[VtkViewer] Could not add orientation axes:', err.message)
  }
}

function applyDisplayMode(actor) {
  const prop = actor.getProperty()
  if (props.displayMode === 'wireframe') {
    prop.setRepresentationToWireframe()
    prop.setEdgeVisibility(false)
  } else if (props.displayMode === 'surface+edges') {
    prop.setRepresentationToSurface()
    prop.setEdgeVisibility(true)
    prop.setEdgeColor(0.2, 0.2, 0.2)
  } else {
    prop.setRepresentationToSurface()
    prop.setEdgeVisibility(false)
  }
}

async function loadData() {
  if (!fullScreenRenderer) return
  const gen = ++loadGeneration  // capture current generation
  statusMsg.value = 'Loading 3D mesh...'

  try {
    const params = new URLSearchParams()
    if (props.sourceFile) params.set('file', props.sourceFile)
    if (props.frame > 0) params.set('frame', String(props.frame))
    const qs = params.toString() ? `?${params.toString()}` : ''
    const url = `${POST_SERVICE_URL}/api/surface/${props.sessionId}/${encodeURIComponent(props.zone)}${qs}`
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const vtpBuffer = await resp.arrayBuffer()

    const reader = vtkXMLPolyDataReader.newInstance()
    reader.parseAsArrayBuffer(vtpBuffer)
    const polydata = reader.getOutputData(0)

    // Identify scalars/vectors + synthesize _x/_y/_z triplets in place
    const info = inspectAndSynthesize(polydata)
    console.log(`[VtkViewer] scalars=${info.scalars.length}, vectors=${info.vectors.length} ${info.vectors.length ? '['+info.vectors.join(',')+']' : ''}`)
    emit('arrays-detected', { scalars: info.scalars, vectors: info.vectors })

    const renderer = fullScreenRenderer.getRenderer()
    const renderWindow = fullScreenRenderer.getRenderWindow()
    renderer.removeAllViewProps()

    currentPolydata = polydata
    currentGlyphMapper = null
    currentVectorMaxMag = null

    if (props.renderMode === 'vector' && props.vectorName) {
      renderVector(polydata, info)
    } else {
      renderScalar(polydata)
    }

    if (!hasLoadedOnce) {
      renderer.resetCamera()
      hasLoadedOnce = true
      // Re-fit camera after container layout stabilizes (panel animation)
      setTimeout(() => {
        if (fullScreenRenderer) {
          fullScreenRenderer.resize()
          renderer.resetCamera()
          renderWindow.render()
        }
      }, 300)
    } else {
      renderer.resetCameraClippingRange()
    }
    renderWindow.render()
    statusMsg.value = ''
    if (gen === loadGeneration) emit('loaded')
  } catch (err) {
    statusMsg.value = `Failed to load: ${err.message}`
    console.error('VtkViewer error:', err)
    if (gen === loadGeneration) emit('loaded')  // still signal so playback doesn't hang
  }
}

// Scalar rendering: colored surface by props.scalarName, with optional
// global scalarRange for cross-frame colorbar consistency.
function renderScalar(polydata) {
  vectorHint.value = ''
  const renderer = fullScreenRenderer.getRenderer()
  const pd = polydata.getPointData()
  const cd = polydata.getCellData()

  const mapper = vtkMapper.newInstance()
  mapper.setInputData(polydata)

  let coloredArrayName = null
  if (props.scalarName) {
    let arr = pd.getArrayByName(props.scalarName)
    let useCellData = false
    if (!arr) {
      arr = cd.getArrayByName(props.scalarName)
      useCellData = true
    }
    if (arr) {
      const [lo, hi] = props.scalarRange || arr.getRange()
      const ctf = vtkColorTransferFunction.newInstance()
      const preset = colorPresets[props.colorPreset] || colorPresets.jet
      for (const [t, r, g, b] of preset) {
        ctf.addRGBPoint(lo + t * (hi - lo), r, g, b)
      }
      if (useCellData) {
        cd.setActiveScalars(props.scalarName)
        mapper.setScalarModeToUseCellData()
      } else {
        pd.setActiveScalars(props.scalarName)
        mapper.setScalarModeToUsePointData()
      }
      mapper.setLookupTable(ctf)
      mapper.setUseLookupTableScalarRange(false)
      mapper.setScalarRange(lo, hi)
      mapper.setScalarVisibility(true)
      mapper.setColorByArrayName(props.scalarName)
      coloredArrayName = props.scalarName

      const bar = vtkScalarBarActor.newInstance()
      bar.setScalarsToColors(ctf)
      bar.setAxisLabel(props.scalarName)
      renderer.addActor(bar)
    } else {
      console.warn(`[VtkViewer] Scalar '${props.scalarName}' not found in polydata`)
    }
  }

  const actor = vtkActor.newInstance()
  actor.setMapper(mapper)
  actor.getProperty().setOpacity(props.opacity)
  if (!coloredArrayName) {
    actor.getProperty().setColor(0.7, 0.7, 0.75)
  }
  applyDisplayMode(actor)
  renderer.addActor(actor)
}

// Vector rendering: translucent base mesh + arrow glyphs oriented by
// props.vectorName, scaled by magnitude, colored by <vec>_Magnitude.
// Glyph count is capped at MAX_ARROWS — large zones are point-strided.
function renderVector(polydata, info) {
  const renderer = fullScreenRenderer.getRenderer()

  let vecInfo = info.vectorsInfo.find(v => v.name === props.vectorName)
  if (!vecInfo) {
    console.warn(`[VtkViewer] Vector '${props.vectorName}' not detected — falling back to scalar render`)
    renderScalar(polydata)
    return
  }

  // Translucent base mesh (always the full geometry)
  const baseMapper = vtkMapper.newInstance()
  baseMapper.setInputData(polydata)
  baseMapper.setScalarVisibility(false)
  const baseActor = vtkActor.newInstance()
  baseActor.setMapper(baseMapper)
  baseActor.getProperty().setColor(0.5, 0.55, 0.6)
  baseActor.getProperty().setOpacity(0.35)
  renderer.addActor(baseActor)

  // Subsample points so the glyph count stays bounded
  const glyphResult = subsampleForGlyphs(polydata, props.vectorName, MAX_ARROWS)
  const glyphInput = glyphResult.polydata
  if (glyphResult.sampled) {
    vectorHint.value = `已抽稀至 ${glyphResult.count} 个箭头（每 ${glyphResult.stride} 点取 1）`
    console.warn(`[VtkViewer] Vector glyphs strided: ${glyphResult.count} arrows (1/${glyphResult.stride})`)
  } else {
    vectorHint.value = ''
  }

  // Glyph mapper + arrow source
  const arrow = vtkArrowSource.newInstance({
    tipResolution: 6, tipRadius: 0.1, tipLength: 0.35,
    shaftResolution: 6, shaftRadius: 0.03,
  })
  const glyphMapper = vtkGlyph3DMapper.newInstance()
  glyphMapper.setInputData(glyphInput, 0)
  glyphMapper.setInputConnection(arrow.getOutputPort(), 1)
  glyphMapper.setOrientationArray(props.vectorName)
  glyphMapper.setOrientationMode(vtkGlyph3DMapper.OrientationModes.DIRECTION)
  glyphMapper.setScaleMode(vtkGlyph3DMapper.ScaleModes.SCALE_BY_MAGNITUDE)
  glyphMapper.setScaleArray(props.vectorName)
  glyphMapper.setScaleFactor(computeAutoScale(polydata, vecInfo.maxMagnitude) * props.arrowScale)

  // Color by magnitude (the synthesized <vec>_Magnitude array)
  const magName = props.vectorName + '_Magnitude'
  const magArr = glyphInput.getPointData().getArrayByName(magName)
  if (magArr) {
    const [lo, hi] = magArr.getRange()
    const ctf = vtkColorTransferFunction.newInstance()
    const preset = colorPresets[props.colorPreset] || colorPresets.jet
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
    bar.setAxisLabel(props.vectorName + ' Magnitude')
    renderer.addActor(bar)
  }

  const actor = vtkActor.newInstance()
  actor.setMapper(glyphMapper)
  actor.getProperty().setAmbient(0.5)
  actor.getProperty().setDiffuse(0.5)
  renderer.addActor(actor)

  currentGlyphMapper = glyphMapper
  currentVectorMaxMag = vecInfo.maxMagnitude
}

async function loadFromFile() {
  if (!fullScreenRenderer || !props.path) return
  statusMsg.value = 'Loading VTP file...'

  try {
    // Encode path but keep slashes intact (browser treats D: as protocol otherwise)
    const safePath = props.path.split('/').map(s => encodeURIComponent(s)).join('/')
    const url = `${POST_SERVICE_URL}/api/file/${safePath}`
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const vtpBuffer = await resp.arrayBuffer()

    const reader = vtkXMLPolyDataReader.newInstance()
    reader.parseAsArrayBuffer(vtpBuffer)
    const polydata = reader.getOutputData(0)

    // Identify scalars/vectors so parent UI can offer vector-mode toggle
    const info = inspectAndSynthesize(polydata)
    emit('arrays-detected', { scalars: info.scalars, vectors: info.vectors })

    currentPolydata = polydata
    currentGlyphMapper = null
    currentVectorMaxMag = null

    const renderer = fullScreenRenderer.getRenderer()
    const renderWindow = fullScreenRenderer.getRenderWindow()
    renderer.removeAllViewProps()

    // Vector mode short-circuit: use the same renderVector path as loadData()
    if (props.renderMode === 'vector' && props.vectorName) {
      renderVector(polydata, info)
      renderer.resetCamera()
      renderWindow.render()
      statusMsg.value = ''
      return
    }

    const mapper = vtkMapper.newInstance()
    mapper.setInputData(polydata)

    // Auto-color by first scalar array if available
    const pd = polydata.getPointData()
    const cd = polydata.getCellData()
    let arr = null
    let arrName = ''
    let useCellData = false

    // Try point data first, then cell data
    if (pd.getNumberOfArrays() > 0) {
      arr = pd.getArrayByIndex(0)
      arrName = arr.getName()
    } else if (cd.getNumberOfArrays() > 0) {
      arr = cd.getArrayByIndex(0)
      arrName = arr.getName()
      useCellData = true
    }

    if (arr && arr.getNumberOfComponents() === 1) {
      const [lo, hi] = arr.getRange()
      console.log(`[VtkViewer] File mode: coloring by '${arrName}', range=[${lo}, ${hi}]`)

      const ctf = vtkColorTransferFunction.newInstance()
      const step = (hi - lo) / 4
      ctf.addRGBPoint(lo, 0.0, 0.0, 1.0)
      ctf.addRGBPoint(lo + step, 0.0, 1.0, 1.0)
      ctf.addRGBPoint(lo + 2 * step, 0.0, 1.0, 0.0)
      ctf.addRGBPoint(lo + 3 * step, 1.0, 1.0, 0.0)
      ctf.addRGBPoint(hi, 1.0, 0.0, 0.0)

      if (useCellData) {
        cd.setActiveScalars(arrName)
        mapper.setScalarModeToUseCellData()
      } else {
        pd.setActiveScalars(arrName)
        mapper.setScalarModeToUsePointData()
      }
      mapper.setLookupTable(ctf)
      mapper.setUseLookupTableScalarRange(false)
      mapper.setScalarRange(lo, hi)
      mapper.setScalarVisibility(true)
      mapper.setColorByArrayName(arrName)

      const bar = vtkScalarBarActor.newInstance()
      bar.setScalarsToColors(ctf)
      bar.setAxisLabel(arrName)
      renderer.addActor(bar)
    }

    const actor = vtkActor.newInstance()
    actor.setMapper(mapper)
    if (!arr) {
      actor.getProperty().setColor(0.5, 0.7, 0.9)
    }
    renderer.addActor(actor)

    renderer.resetCamera()
    renderWindow.render()
    statusMsg.value = ''
  } catch (err) {
    statusMsg.value = `Failed to load file: ${err.message}`
    console.error('VtkViewer loadFromFile error:', err)
  }
}

// Capture the current render as a PNG data URL. Used by frame-sequence
// export (parent drives setFrame → waits 'loaded' → calls captureFrame).
async function captureFrame() {
  if (!fullScreenRenderer) return null
  const renderWindow = fullScreenRenderer.getRenderWindow()
  renderWindow.render()
  const images = renderWindow.captureImages('image/png')
  if (!images || !images.length) return null
  return await images[0]
}

defineExpose({ captureFrame })
</script>

<template>
  <div class="vtk-viewer">
    <div class="viewer-label" v-if="path || zone">
      <span>3D Viewer</span>
      <span v-if="zone" class="viewer-path mono">{{ zone }}{{ scalarName ? ' · ' + scalarName : '' }}</span>
      <span v-else-if="path" class="viewer-path mono">{{ path }}</span>
    </div>
    <div class="viewer-container" ref="containerRef">
      <div v-if="statusMsg" class="viewer-overlay">{{ statusMsg }}</div>
      <div v-if="vectorHint" class="vector-hint">{{ vectorHint }}</div>
      <div class="viewer-hints">
        <span class="hint-item">Drag: Rotate</span>
        <span class="hint-sep">|</span>
        <span class="hint-item">Shift+Drag: Pan</span>
        <span class="hint-sep">|</span>
        <span class="hint-item">Scroll: Zoom</span>
        <span class="hint-sep">|</span>
        <span class="hint-item"><kbd>R</kbd> Reset</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.vtk-viewer {
  background: var(--bg-tertiary);
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.viewer-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.viewer-path {
  font-weight: 400;
  color: var(--text-muted);
  font-size: 11px;
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
  z-index: 1;
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

.vector-hint {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(180, 120, 0, 0.85);
  color: #fff;
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 6px;
  pointer-events: none;
  z-index: 2;
  white-space: nowrap;
}
</style>
