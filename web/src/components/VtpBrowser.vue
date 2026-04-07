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
})

const containerRef = ref(null)
const statusMsg = ref('')
const scalarNames = ref([])
const selectedScalar = ref('')

let fullScreenRenderer = null
let loadedPolydata = null

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

function initViewer() {
  if (!containerRef.value) return
  fullScreenRenderer = vtkFullScreenRenderWindow.newInstance({
    rootContainer: containerRef.value,
    containerStyle: { width: '100%', height: '100%' },
    background: [0.95, 0.95, 0.93],
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

async function loadVtp() {
  if (!fullScreenRenderer || !props.path) return
  statusMsg.value = 'Loading...'

  try {
    const safePath = props.path.split('/').map(s => encodeURIComponent(s)).join('/')
    const url = `http://localhost:8000/api/file/${safePath}`
    const resp = await fetch(url)
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
      selectedScalar.value = names[0].name
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
      const step = (hi - lo) / 4
      ctf.addRGBPoint(lo, 0.0, 0.0, 1.0)
      ctf.addRGBPoint(lo + step, 0.0, 1.0, 1.0)
      ctf.addRGBPoint(lo + 2 * step, 0.0, 1.0, 0.0)
      ctf.addRGBPoint(lo + 3 * step, 1.0, 1.0, 0.0)
      ctf.addRGBPoint(hi, 1.0, 0.0, 0.0)

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
  if (!scalarInfo) {
    actor.getProperty().setColor(0.5, 0.7, 0.9)
  }
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
    </div>
    <div class="viewer-container" ref="containerRef">
      <div v-if="statusMsg" class="viewer-overlay">{{ statusMsg }}</div>
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
</style>
