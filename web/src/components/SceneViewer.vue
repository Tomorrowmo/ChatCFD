<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { POST_SERVICE_URL } from '../config.js'
import { useChatStore } from '../stores/chat.js'
import LayerPanel from './LayerPanel.vue'
import TimeControls from './TimeControls.vue'

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

const { activeSceneLayers, activeConversation } = useChatStore()

const containerRef = ref(null)
const statusMsg = ref('')
const currentFrame = ref(0)
const timeControlsRef = ref(null)
const zoneScalarRanges = ref({})   // {zone: {scalar: [min, max]}} from backend
const fileLayerRanges = ref({})    // {layerId: {scalar: [min, max]}} precomputed

const frameCount = computed(() => props.meshData?.frame_count || 1)
const timeLabels = computed(() => props.meshData?.time_labels || [])

let fullScreenRenderer = null
let hasLoadedOnce = false
// layerId -> { actor, scalarBarActor, polydata }
const layerMap = new Map()

onMounted(() => {
  initViewer()
  fetchZoneScalarRanges()
})

watch(() => props.meshData, () => { fetchZoneScalarRanges() })

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
    background: [0.92, 0.93, 0.95],
  })
  // Prevent browser auto-scroll on middle mouse so VTK.js pan works
  containerRef.value.addEventListener('mousedown', (e) => {
    if (e.button === 1) e.preventDefault()
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

async function fetchZoneScalarRanges() {
  if (!props.meshData || frameCount.value <= 1) return
  const sid = activeConversation.value?.id || 'default'
  const sf = props.meshData?.file_path || ''
  try {
    const params = sf ? `?file=${encodeURIComponent(sf)}` : ''
    const resp = await fetch(`${POST_SERVICE_URL}/api/zones/${sid}${params}`)
    if (!resp.ok) return
    const data = await resp.json()
    if (data.scalar_ranges) {
      zoneScalarRanges.value = data.scalar_ranges
    } else if (data.frame_count > 1) {
      setTimeout(fetchZoneScalarRanges, 3000)
    }
  } catch { /* ignore */ }
}

async function precomputeFileLayerRanges(layer) {
  const frameFiles = layer.source?.outputFilesByFrame
  if (!frameFiles || frameFiles.length <= 1) return
  const ranges = {}
  for (const filePath of frameFiles) {
    try {
      const safePath = filePath.split('/').map(s => encodeURIComponent(s)).join('/')
      const resp = await fetch(`${POST_SERVICE_URL}/api/file/${safePath}`)
      if (!resp.ok) continue
      const buffer = await resp.arrayBuffer()
      const reader = vtkXMLPolyDataReader.newInstance()
      reader.parseAsArrayBuffer(buffer)
      const pd = reader.getOutputData(0)
      for (const dataObj of [pd.getPointData(), pd.getCellData()]) {
        for (let i = 0; i < dataObj.getNumberOfArrays(); i++) {
          const arr = dataObj.getArrayByIndex(i)
          if (arr.getNumberOfComponents() !== 1) continue
          const name = arr.getName()
          const [lo, hi] = arr.getRange()
          if (name in ranges) {
            ranges[name][0] = Math.min(ranges[name][0], lo)
            ranges[name][1] = Math.max(ranges[name][1], hi)
          } else {
            ranges[name] = [lo, hi]
          }
        }
      }
    } catch { /* skip */ }
  }
  fileLayerRanges.value = { ...fileLayerRanges.value, [layer.id]: ranges }
}

function getLayerGlobalRange(layer, scalarName) {
  if (!scalarName) return null
  if (layer.type === 'zone') {
    const zr = zoneScalarRanges.value[layer.source.zone]
    return zr?.[scalarName] || null
  }
  const fr = fileLayerRanges.value[layer.id]
  return fr?.[scalarName] || null
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

async function fetchVtpBuffer(layer, frame = 0) {
  if (layer.type === 'zone') {
    const { sessionId, zone, sourceFile } = layer.source
    const params = new URLSearchParams()
    if (sourceFile) params.set('file', sourceFile)
    if (frame > 0) params.set('frame', String(frame))
    const qs = params.toString() ? `?${params}` : ''
    const url = `${POST_SERVICE_URL}/api/surface/${sessionId}/${encodeURIComponent(zone)}${qs}`
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status} fetching zone ${zone}`)
    return resp.arrayBuffer()
  } else {
    // For file-type layers, check for per-frame file paths
    const frameFiles = layer.source.outputFilesByFrame
    let filePath = layer.source.filePath
    if (frameFiles && frameFiles.length > frame) {
      filePath = frameFiles[frame]
    }
    const safePath = filePath.split('/').map(s => encodeURIComponent(s)).join('/')
    const url = `${POST_SERVICE_URL}/api/file/${safePath}`
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status} fetching file`)
    return resp.arrayBuffer()
  }
}

function createActorFromPolydata(polydata, scalarName, globalRange = null) {
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
      const perFrame = arr.getRange()
      const [lo, hi] = globalRange || perFrame
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

  return { actor, scalarBarActor, mapper, resolvedScalar: targetScalar }
}

async function addLayerToScene(layer, frame = 0) {
  if (!fullScreenRenderer) return
  if (layerMap.has(layer.id)) return // already loaded

  // Kick off background precompute for file layers with multi-frame
  if (layer.type === 'file' && layer.source?.outputFilesByFrame?.length > 1) {
    precomputeFileLayerRanges(layer)
  }

  try {
    const buffer = await fetchVtpBuffer(layer, frame)
    const reader = vtkXMLPolyDataReader.newInstance()
    reader.parseAsArrayBuffer(buffer)
    const polydata = reader.getOutputData(0)

    const scalarName = layer.type === 'zone' ? (layer.source.scalarName || '') : ''
    const globalRange = getLayerGlobalRange(layer, scalarName)
    const { actor, scalarBarActor, mapper, resolvedScalar } = createActorFromPolydata(polydata, scalarName, globalRange)

    actor.setVisibility(layer.visible)
    if (scalarBarActor) scalarBarActor.setVisibility(layer.visible)

    const renderer = fullScreenRenderer.getRenderer()
    renderer.addActor(actor)
    if (scalarBarActor) renderer.addActor(scalarBarActor)

    layerMap.set(layer.id, { actor, scalarBarActor, mapper, polydata, scalarName: resolvedScalar })

    console.log(`[SceneViewer] Added layer: ${layer.name} (${layer.id})`)
  } catch (err) {
    console.error(`[SceneViewer] Failed to add layer ${layer.name}:`, err)
  }
}

async function reloadLayerData(layer, frame) {
  if (!fullScreenRenderer) return
  const entry = layerMap.get(layer.id)
  if (!entry) return

  try {
    const buffer = await fetchVtpBuffer(layer, frame)
    const reader = vtkXMLPolyDataReader.newInstance()
    reader.parseAsArrayBuffer(buffer)
    const polydata = reader.getOutputData(0)

    // Update mapper input data in-place (keeps actor/visibility intact)
    entry.mapper.setInputData(polydata)

    // Update scalar coloring with global range (consistent across frames)
    const scalarName = entry.scalarName || (layer.type === 'zone' ? (layer.source.scalarName || '') : '')
    if (scalarName) {
      const pd = polydata.getPointData()
      const cd = polydata.getCellData()
      let arr = pd.getArrayByName(scalarName)
      let useCellData = false
      if (!arr) { arr = cd.getArrayByName(scalarName); useCellData = true }
      if (arr && arr.getNumberOfComponents() === 1) {
        const perFrame = arr.getRange()
        const globalRange = getLayerGlobalRange(layer, scalarName)
        const [lo, hi] = globalRange || perFrame
        const ctf = buildRainbowLut(lo, hi)
        entry.mapper.setLookupTable(ctf)
        entry.mapper.setScalarRange(lo, hi)
        if (entry.scalarBarActor) entry.scalarBarActor.setScalarsToColors(ctf)
      }
    }

    entry.polydata = polydata
  } catch (err) {
    console.error(`[SceneViewer] Failed to reload layer ${layer.name} frame ${frame}:`, err)
  }
}

async function reloadAllLayers(frame) {
  const layers = activeSceneLayers.value
  if (!layers.length || !fullScreenRenderer) {
    timeControlsRef.value?.frameReady()
    return
  }

  await Promise.all(layers.map(layer => reloadLayerData(layer, frame)))

  if (!hasLoadedOnce) {
    fullScreenRenderer.getRenderer().resetCamera()
    hasLoadedOnce = true
  } else {
    fullScreenRenderer.getRenderer().resetCameraClippingRange()
  }
  renderScene()
  timeControlsRef.value?.frameReady()
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

// When frame changes, reload all layer data for the new frame
watch(currentFrame, (frame) => {
  reloadAllLayers(frame)
})

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
        await addLayerToScene(layer, currentFrame.value)
        needsResetCamera = true
      } else {
        setLayerVisibility(layer.id, layer.visible)
      }
    }

    if (needsResetCamera) {
      fullScreenRenderer.getRenderer().resetCamera()
      hasLoadedOnce = true
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
        await addLayerToScene(layer, currentFrame.value)
      }
    }
    if (fullScreenRenderer) {
      fullScreenRenderer.getRenderer().resetCamera()
      hasLoadedOnce = true
      renderScene()
    }
  }
})
</script>

<template>
  <div class="scene-viewer">
    <TimeControls
      v-if="frameCount > 1"
      ref="timeControlsRef"
      :frameCount="frameCount"
      :timeLabels="timeLabels"
      v-model="currentFrame"
    />
    <div class="viewer-container" ref="containerRef">
      <div v-if="statusMsg" class="viewer-overlay">{{ statusMsg }}</div>
    </div>
    <LayerPanel :meshData="meshData" :sourceFile="meshData?.file_path || ''" />
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
