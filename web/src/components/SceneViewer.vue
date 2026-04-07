<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useChatStore } from '../stores/chat.js'
import LayerPanel from './LayerPanel.vue'

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
  /** loadFile data (zones array) for the "Add Zone" dropdown in LayerPanel */
  meshData: { type: Object, default: null },
})

const { activeSceneLayers } = useChatStore()

const containerRef = ref(null)
const statusMsg = ref('')

let fullScreenRenderer = null
// layerId -> { actor, scalarBarActor, polydata }
const layerMap = new Map()

onMounted(() => {
  initViewer()
})

onBeforeUnmount(() => {
  layerMap.clear()
  if (fullScreenRenderer) {
    fullScreenRenderer.delete()
    fullScreenRenderer = null
  }
})

function initViewer() {
  if (!containerRef.value) return
  fullScreenRenderer = vtkFullScreenRenderWindow.newInstance({
    rootContainer: containerRef.value,
    containerStyle: { width: '100%', height: '100%' },
    background: [0.15, 0.15, 0.18],
  })
  addOrientationAxes()
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
    console.warn('[SceneViewer] Could not add orientation axes:', err.message)
  }
}

function buildRainbowLut(lo, hi) {
  const ctf = vtkColorTransferFunction.newInstance()
  const step = (hi - lo) / 4
  ctf.addRGBPoint(lo, 0.0, 0.0, 1.0)
  ctf.addRGBPoint(lo + step, 0.0, 1.0, 1.0)
  ctf.addRGBPoint(lo + 2 * step, 0.0, 1.0, 0.0)
  ctf.addRGBPoint(lo + 3 * step, 1.0, 1.0, 0.0)
  ctf.addRGBPoint(hi, 1.0, 0.0, 0.0)
  return ctf
}

async function fetchVtpBuffer(layer) {
  if (layer.type === 'zone') {
    const { sessionId, zone } = layer.source
    const url = `http://localhost:8000/api/surface/${sessionId}/${encodeURIComponent(zone)}`
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status} fetching zone ${zone}`)
    return resp.arrayBuffer()
  } else {
    const safePath = layer.source.filePath.split('/').map(s => encodeURIComponent(s)).join('/')
    const url = `http://localhost:8000/api/file/${safePath}`
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status} fetching file`)
    return resp.arrayBuffer()
  }
}

function createActorFromPolydata(polydata, scalarName) {
  const mapper = vtkMapper.newInstance()
  mapper.setInputData(polydata)

  const pd = polydata.getPointData()
  const cd = polydata.getCellData()
  let scalarBarActor = null

  // Determine which scalar to color by
  let targetScalar = scalarName || ''
  if (!targetScalar) {
    // Auto-pick first 1-component scalar
    for (let i = 0; i < pd.getNumberOfArrays(); i++) {
      const a = pd.getArrayByIndex(i)
      if (a.getNumberOfComponents() === 1) { targetScalar = a.getName(); break }
    }
    if (!targetScalar) {
      for (let i = 0; i < cd.getNumberOfArrays(); i++) {
        const a = cd.getArrayByIndex(i)
        if (a.getNumberOfComponents() === 1) { targetScalar = a.getName(); break }
      }
    }
  }

  if (targetScalar) {
    let arr = pd.getArrayByName(targetScalar)
    let useCellData = false
    if (!arr) {
      arr = cd.getArrayByName(targetScalar)
      useCellData = true
    }
    if (arr && arr.getNumberOfComponents() === 1) {
      const [lo, hi] = arr.getRange()
      const ctf = buildRainbowLut(lo, hi)

      if (useCellData) {
        cd.setActiveScalars(targetScalar)
        mapper.setScalarModeToUseCellData()
      } else {
        pd.setActiveScalars(targetScalar)
        mapper.setScalarModeToUsePointData()
      }
      mapper.setLookupTable(ctf)
      mapper.setUseLookupTableScalarRange(false)
      mapper.setScalarRange(lo, hi)
      mapper.setScalarVisibility(true)
      mapper.setColorByArrayName(targetScalar)

      scalarBarActor = vtkScalarBarActor.newInstance()
      scalarBarActor.setScalarsToColors(ctf)
      scalarBarActor.setAxisLabel(targetScalar)
    }
  }

  const actor = vtkActor.newInstance()
  actor.setMapper(mapper)
  if (!scalarBarActor) {
    actor.getProperty().setColor(0.7, 0.7, 0.75)
  }

  return { actor, scalarBarActor, mapper }
}

async function addLayerToScene(layer) {
  if (!fullScreenRenderer) return
  if (layerMap.has(layer.id)) return // already loaded

  try {
    const buffer = await fetchVtpBuffer(layer)
    const reader = vtkXMLPolyDataReader.newInstance()
    reader.parseAsArrayBuffer(buffer)
    const polydata = reader.getOutputData(0)

    const scalarName = layer.type === 'zone' ? (layer.source.scalarName || '') : ''
    const { actor, scalarBarActor, mapper } = createActorFromPolydata(polydata, scalarName)

    actor.setVisibility(layer.visible)
    if (scalarBarActor) scalarBarActor.setVisibility(layer.visible)

    const renderer = fullScreenRenderer.getRenderer()
    renderer.addActor(actor)
    if (scalarBarActor) renderer.addActor(scalarBarActor)

    layerMap.set(layer.id, { actor, scalarBarActor, mapper, polydata })

    console.log(`[SceneViewer] Added layer: ${layer.name} (${layer.id})`)
  } catch (err) {
    console.error(`[SceneViewer] Failed to add layer ${layer.name}:`, err)
  }
}

function removeLayerFromScene(layerId) {
  if (!fullScreenRenderer) return
  const entry = layerMap.get(layerId)
  if (!entry) return

  const renderer = fullScreenRenderer.getRenderer()
  renderer.removeActor(entry.actor)
  if (entry.scalarBarActor) renderer.removeActor(entry.scalarBarActor)
  layerMap.delete(layerId)
  console.log(`[SceneViewer] Removed layer: ${layerId}`)
}

function setLayerVisibility(layerId, visible) {
  const entry = layerMap.get(layerId)
  if (!entry) return
  entry.actor.setVisibility(visible)
  if (entry.scalarBarActor) entry.scalarBarActor.setVisibility(visible)
}

function renderScene() {
  if (!fullScreenRenderer) return
  fullScreenRenderer.getRenderWindow().render()
}

// Sync layers from store to VTK scene
watch(
  activeSceneLayers,
  async (layers) => {
    if (!fullScreenRenderer) return

    const currentIds = new Set(layerMap.keys())
    const targetIds = new Set(layers.map(l => l.id))

    // Remove layers no longer in store
    for (const id of currentIds) {
      if (!targetIds.has(id)) {
        removeLayerFromScene(id)
      }
    }

    // Add new layers and update visibility
    let needsResetCamera = false
    for (const layer of layers) {
      if (!layerMap.has(layer.id)) {
        await addLayerToScene(layer)
        needsResetCamera = true
      } else {
        setLayerVisibility(layer.id, layer.visible)
      }
    }

    if (needsResetCamera) {
      fullScreenRenderer.getRenderer().resetCamera()
    }
    renderScene()
  },
  { deep: true }
)

// Initial load of any existing layers after mount
onMounted(async () => {
  await nextTick()
  const layers = activeSceneLayers.value
  if (layers.length > 0) {
    for (const layer of layers) {
      if (!layerMap.has(layer.id)) {
        await addLayerToScene(layer)
      }
    }
    if (fullScreenRenderer) {
      fullScreenRenderer.getRenderer().resetCamera()
      renderScene()
    }
  }
})
</script>

<template>
  <div class="scene-viewer">
    <div class="viewer-container" ref="containerRef">
      <div v-if="statusMsg" class="viewer-overlay">{{ statusMsg }}</div>
    </div>
    <LayerPanel :meshData="meshData" />
  </div>
</template>

<style scoped>
.scene-viewer {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  background: var(--bg-tertiary);
  border-radius: 10px;
  overflow: hidden;
}

.viewer-container {
  position: relative;
  width: 100%;
  flex: 1;
  min-height: 300px;
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
</style>
