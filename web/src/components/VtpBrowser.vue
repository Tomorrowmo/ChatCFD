<script setup>
import { ref, watch, computed, onMounted, onBeforeUnmount } from 'vue'

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
  path: { type: String, required: true },
  sessionId: { type: String, default: '' },
  baseZone: { type: String, default: '' },  // wall/tri zone name → load as background model
})

const containerRef = ref(null)
const statusMsg = ref('')
const scalarNames = ref([])
const selectedScalar = ref('')
const opacity = ref(1.0)
const selectedPreset = ref('jet')

const colorPresets = {
  jet:         [[0,0,0,1], [0.25,0,1,1], [0.5,0,1,0], [0.75,1,1,0], [1,1,0,0]],
  coolwarm:    [[0,0.231,0.298,0.753], [0.5,0.865,0.865,0.865], [1,0.706,0.016,0.150]],
  rainbow:     [[0,0.278,0,0.714], [0.25,0,0,1], [0.5,0,1,0], [0.75,1,1,0], [1,1,0,0]],
  viridis:     [[0,0.267,0.004,0.329], [0.25,0.282,0.141,0.457], [0.5,0.127,0.566,0.550], [0.75,0.544,0.774,0.247], [1,0.993,0.906,0.144]],
  grayscale:   [[0,0,0,0], [1,1,1,1]],
  blueRed:     [[0,0,0,1], [1,1,0,0]],
}

let fullScreenRenderer = null
let loadedPolydata = null
let currentActor = null
let baseModelPolydata = null

onMounted(() => {
  initViewer()
  addOrientationAxes()
  loadVtp()
})

onBeforeUnmount(() => {
  if (fullScreenRenderer) {
    fullScreenRenderer.delete()
    fullScreenRenderer = null
  }
})

watch(() => props.path, () => { loadVtp() })
watch(selectedScalar, () => { if (loadedPolydata) renderPolydata() })
watch(selectedPreset, () => { if (loadedPolydata) renderPolydata() })
watch(opacity, (val) => {
  if (currentActor) {
    currentActor.getProperty().setOpacity(val)
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

async function loadBaseModel() {
  if (!props.sessionId || !props.baseZone) return
  try {
    const url = `http://localhost:8000/api/surface/${props.sessionId}/${encodeURIComponent(props.baseZone)}`
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
  if (!fullScreenRenderer || !props.path) return
  statusMsg.value = 'Loading...'

  try {
    // Load base model and result in parallel
    const safePath = props.path.split('/').map(s => encodeURIComponent(s)).join('/')
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

    // Collect scalar names (1-component arrays only)
    const names = []
    const pd = loadedPolydata.getPointData()
    const cd = loadedPolydata.getCellData()
    for (let i = 0; i < pd.getNumberOfArrays(); i++) {
      const a = pd.getArrayByIndex(i)
      if (a.getNumberOfComponents() === 1) names.push({ name: a.getName(), loc: 'point' })
    }
    for (let i = 0; i < cd.getNumberOfArrays(); i++) {
      const a = cd.getArrayByIndex(i)
      if (a.getNumberOfComponents() === 1) names.push({ name: a.getName(), loc: 'cell' })
    }
    scalarNames.value = names
    if (names.length && !selectedScalar.value) {
      // Prefer VelocityMagnitude as default (most useful for streamlines)
      const preferred = names.find(s => s.name === 'VelocityMagnitude')
      selectedScalar.value = preferred ? preferred.name : names[0].name
    }

    renderPolydata()
  } catch (err) {
    statusMsg.value = `Failed: ${err.message}`
    console.error('VtpBrowser error:', err)
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
      const [lo, hi] = arr.getRange()
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
  renderer.resetCamera()
  renderWindow.render()
  statusMsg.value = ''
}
</script>

<template>
  <div class="vtp-browser">
    <div class="controls" v-if="scalarNames.length">
      <label>
        Scalar:
        <select v-model="selectedScalar">
          <option value="">None (geometry)</option>
          <option v-for="s in scalarNames" :key="s.name" :value="s.name">
            {{ s.name }}
          </option>
        </select>
      </label>
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
      <label class="opacity-label">
        Opacity:
        <input type="range" v-model.number="opacity" min="0" max="1" step="0.05" class="opacity-slider" />
        <span class="opacity-value">{{ Math.round(opacity * 100) }}%</span>
      </label>
    </div>
    <div class="viewer-container" ref="containerRef">
      <div v-if="statusMsg" class="viewer-overlay">{{ statusMsg }}</div>
      <div class="viewer-hints">
        <span class="hint-item"><kbd>L</kbd> Rotate</span>
        <span class="hint-sep">|</span>
        <span class="hint-item"><kbd>M</kbd> Pan</span>
        <span class="hint-sep">|</span>
        <span class="hint-item"><kbd>&#x2191;&#x2193;</kbd> Zoom</span>
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
