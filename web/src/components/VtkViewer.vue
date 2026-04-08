<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'

import '@kitware/vtk.js/Rendering/Profiles/Geometry'
import vtkFullScreenRenderWindow from '@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow'
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor'
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper'
import vtkXMLPolyDataReader from '@kitware/vtk.js/IO/XML/XMLPolyDataReader'
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction'
import vtkScalarBarActor from '@kitware/vtk.js/Rendering/Core/ScalarBarActor'
import vtkAxesActor from '@kitware/vtk.js/Rendering/Core/AxesActor'
import vtkOrientationMarkerWidget from '@kitware/vtk.js/Interaction/Widgets/OrientationMarkerWidget'

const props = defineProps({
  sessionId: { type: String, default: 'default' },
  zone: { type: String, default: '' },
  scalarName: { type: String, default: '' },
  path: { type: String, default: '' },
  displayMode: { type: String, default: 'surface' },
  opacity: { type: Number, default: 1.0 },
  colorPreset: { type: String, default: 'jet' },
})

const colorPresets = {
  jet:         [[0,0,0,1], [0.25,0,1,1], [0.5,0,1,0], [0.75,1,1,0], [1,1,0,0]],
  coolwarm:    [[0,0.231,0.298,0.753], [0.5,0.865,0.865,0.865], [1,0.706,0.016,0.150]],
  rainbow:     [[0,0.278,0,0.714], [0.25,0,0,1], [0.5,0,1,0], [0.75,1,1,0], [1,1,0,0]],
  viridis:     [[0,0.267,0.004,0.329], [0.25,0.282,0.141,0.457], [0.5,0.127,0.566,0.550], [0.75,0.544,0.774,0.247], [1,0.993,0.906,0.144]],
  grayscale:   [[0,0,0,0], [1,1,1,1]],
  blueRed:     [[0,0,0,1], [1,1,0,0]],
}

const containerRef = ref(null)
const statusMsg = ref('')
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
  () => [props.sessionId, props.zone, props.scalarName],
  () => {
    if (props.zone) loadData()
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
  statusMsg.value = 'Loading 3D mesh...'

  try {
    const url = `http://localhost:8000/api/surface/${props.sessionId}/${encodeURIComponent(props.zone)}`
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const vtpBuffer = await resp.arrayBuffer()

    const reader = vtkXMLPolyDataReader.newInstance()
    reader.parseAsArrayBuffer(vtpBuffer)
    const polydata = reader.getOutputData(0)

    // Debug: list available arrays
    const pointArrNames = []
    const cellArrNames = []
    const pd = polydata.getPointData()
    const cd = polydata.getCellData()
    for (let i = 0; i < pd.getNumberOfArrays(); i++) pointArrNames.push(pd.getArrayByIndex(i).getName())
    for (let i = 0; i < cd.getNumberOfArrays(); i++) cellArrNames.push(cd.getArrayByIndex(i).getName())
    console.log('[VtkViewer] Loaded polydata. Point arrays:', pointArrNames, 'Cell arrays:', cellArrNames)
    console.log('[VtkViewer] Requested scalar:', props.scalarName)

    const renderer = fullScreenRenderer.getRenderer()
    const renderWindow = fullScreenRenderer.getRenderWindow()

    // Clear previous actors / scalar bars
    renderer.removeAllViewProps()

    const mapper = vtkMapper.newInstance()
    mapper.setInputData(polydata)

    // Apply scalar coloring if requested
    let coloredArrayName = null
    if (props.scalarName) {
      let arr = pd.getArrayByName(props.scalarName)
      let useCellData = false
      if (!arr) {
        arr = cd.getArrayByName(props.scalarName)
        useCellData = true
      }
      if (arr) {
        const [lo, hi] = arr.getRange()
        console.log(`[VtkViewer] Found scalar '${props.scalarName}' (${useCellData ? 'cell' : 'point'}), range=[${lo}, ${hi}]`)

        // Build LUT from color preset
        const ctf = vtkColorTransferFunction.newInstance()
        const preset = colorPresets[props.colorPreset] || colorPresets.jet
        for (const [t, r, g, b] of preset) {
          ctf.addRGBPoint(lo + t * (hi - lo), r, g, b)
        }

        // VTK.js scalar coloring: set active scalar on the dataset, then wire mapper
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

        // Scalar bar
        const bar = vtkScalarBarActor.newInstance()
        bar.setScalarsToColors(ctf)
        bar.setAxisLabel(props.scalarName)
        renderer.addActor(bar)
      } else {
        console.warn(`[VtkViewer] Scalar '${props.scalarName}' NOT FOUND in polydata. Available point arrays:`, pointArrNames, 'cell arrays:', cellArrNames)
      }
    }

    const actor = vtkActor.newInstance()
    actor.setMapper(mapper)
    actor.getProperty().setOpacity(props.opacity)
    if (!coloredArrayName) {
      actor.getProperty().setColor(0.7, 0.7, 0.75)
    }
    // Apply display mode
    applyDisplayMode(actor)
    renderer.addActor(actor)

    renderer.resetCamera()
    renderWindow.render()
    // Re-fit camera after container layout stabilizes (panel animation)
    setTimeout(() => {
      if (fullScreenRenderer) {
        fullScreenRenderer.resize()
        renderer.resetCamera()
        renderWindow.render()
      }
    }, 300)
    statusMsg.value = ''
  } catch (err) {
    statusMsg.value = `Failed to load: ${err.message}`
    console.error('VtkViewer error:', err)
  }
}

async function loadFromFile() {
  if (!fullScreenRenderer || !props.path) return
  statusMsg.value = 'Loading VTP file...'

  try {
    // Encode path but keep slashes intact (browser treats D: as protocol otherwise)
    const safePath = props.path.split('/').map(s => encodeURIComponent(s)).join('/')
    const url = `http://localhost:8000/api/file/${safePath}`
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const vtpBuffer = await resp.arrayBuffer()

    const reader = vtkXMLPolyDataReader.newInstance()
    reader.parseAsArrayBuffer(vtpBuffer)
    const polydata = reader.getOutputData(0)

    const renderer = fullScreenRenderer.getRenderer()
    const renderWindow = fullScreenRenderer.getRenderWindow()
    renderer.removeAllViewProps()

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
      <div class="viewer-hints">
        <span class="hint-item"><kbd>L</kbd> Rotate</span>
        <span class="hint-sep">|</span>
        <span class="hint-item"><kbd>M</kbd> Pan</span>
        <span class="hint-sep">|</span>
        <span class="hint-item"><kbd>&#x2191;&#x2193;</kbd> Zoom</span>
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
</style>
