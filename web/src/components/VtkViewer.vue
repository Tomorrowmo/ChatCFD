<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'

import '@kitware/vtk.js/Rendering/Profiles/Geometry'
import vtkFullScreenRenderWindow from '@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow'
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor'
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper'
import vtkXMLPolyDataReader from '@kitware/vtk.js/IO/XML/XMLPolyDataReader'
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction'
import vtkScalarBarActor from '@kitware/vtk.js/Rendering/Core/ScalarBarActor'

const props = defineProps({
  sessionId: { type: String, default: 'default' },
  zone: { type: String, default: '' },
  scalarName: { type: String, default: '' },
  path: { type: String, default: '' },
})

const containerRef = ref(null)
const statusMsg = ref('')
let fullScreenRenderer = null

onMounted(() => {
  initViewer()
  if (props.path) loadFromFile()
  else if (props.zone) loadData()
  else statusMsg.value = 'Select a zone to view'
})

onBeforeUnmount(() => {
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
    background: [0.1, 0.1, 0.13],
  })
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

        // Build rainbow LUT
        const ctf = vtkColorTransferFunction.newInstance()
        const step = (hi - lo) / 4
        ctf.addRGBPoint(lo, 0.0, 0.0, 1.0)                 // blue
        ctf.addRGBPoint(lo + step, 0.0, 1.0, 1.0)          // cyan
        ctf.addRGBPoint(lo + 2 * step, 0.0, 1.0, 0.0)      // green
        ctf.addRGBPoint(lo + 3 * step, 1.0, 1.0, 0.0)      // yellow
        ctf.addRGBPoint(hi, 1.0, 0.0, 0.0)                 // red

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
    // If no scalar colored, give a neutral surface color (not red)
    if (!coloredArrayName) {
      actor.getProperty().setColor(0.7, 0.7, 0.75)
    }
    renderer.addActor(actor)

    renderer.resetCamera()
    renderWindow.render()
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
    const url = `http://localhost:8000/api/file/${props.path}`
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
</style>
