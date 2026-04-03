<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'

// VTK.js imports
import '@kitware/vtk.js/Rendering/Profiles/Geometry'
import vtkFullScreenRenderWindow from '@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow'
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor'
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper'
import vtkPolyData from '@kitware/vtk.js/Common/DataModel/PolyData'
import vtkPoints from '@kitware/vtk.js/Common/Core/Points'
import vtkCellArray from '@kitware/vtk.js/Common/Core/CellArray'
import vtkDataArray from '@kitware/vtk.js/Common/Core/DataArray'
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction'

import { useApi } from '../composables/useApi.js'

const props = defineProps({
  sessionId: { type: String, default: '' },
  zone: { type: String, default: '' },
  scalarName: { type: String, default: '' },
  path: { type: String, default: '' },
})

const containerRef = ref(null)
const statusMsg = ref('Initializing 3D Viewer...')
const hasData = ref(false)

let fullScreenRenderer = null

const api = useApi()

onMounted(() => {
  initViewer()
  if (props.sessionId && props.zone) {
    loadData()
  } else {
    showPlaceholder()
  }
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
    if (props.sessionId && props.zone) {
      loadData()
    }
  }
)

function initViewer() {
  if (!containerRef.value) return

  fullScreenRenderer = vtkFullScreenRenderWindow.newInstance({
    rootContainer: containerRef.value,
    containerStyle: {
      width: '100%',
      height: '100%',
    },
    background: [0.1, 0.1, 0.13],
  })
}

function showPlaceholder() {
  if (!fullScreenRenderer) return

  // Create a simple demo cube to show the viewer is working
  const renderer = fullScreenRenderer.getRenderer()
  const renderWindow = fullScreenRenderer.getRenderWindow()

  const polydata = vtkPolyData.newInstance()
  const points = vtkPoints.newInstance()

  // Simple cube vertices
  const vertices = new Float32Array([
    -1, -1, -1,  1, -1, -1,  1,  1, -1,  -1,  1, -1,
    -1, -1,  1,  1, -1,  1,  1,  1,  1,  -1,  1,  1,
  ])
  points.setData(vertices, 3)
  polydata.setPoints(points)

  // Cube faces as triangles
  const cells = new Uint32Array([
    4, 0, 1, 2, 3,
    4, 4, 5, 6, 7,
    4, 0, 1, 5, 4,
    4, 2, 3, 7, 6,
    4, 0, 3, 7, 4,
    4, 1, 2, 6, 5,
  ])
  const polys = vtkCellArray.newInstance()
  polys.setData(cells)
  polydata.setPolys(polys)

  // Add scalar data for coloring
  const scalars = vtkDataArray.newInstance({
    name: 'DemoScalar',
    values: new Float32Array([0, 0.14, 0.29, 0.43, 0.57, 0.71, 0.86, 1.0]),
    numberOfComponents: 1,
  })
  polydata.getPointData().setScalars(scalars)

  const ctf = vtkColorTransferFunction.newInstance()
  ctf.addRGBPoint(0.0, 0.0, 0.0, 1.0)
  ctf.addRGBPoint(0.5, 0.0, 1.0, 0.0)
  ctf.addRGBPoint(1.0, 1.0, 0.0, 0.0)

  const mapper = vtkMapper.newInstance()
  mapper.setInputData(polydata)
  mapper.setLookupTable(ctf)
  mapper.setScalarRange(0, 1)

  const actor = vtkActor.newInstance()
  actor.setMapper(mapper)
  actor.getProperty().setEdgeVisibility(true)
  actor.getProperty().setEdgeColor(0.3, 0.3, 0.35)

  renderer.addActor(actor)
  renderer.resetCamera()
  renderWindow.render()

  hasData.value = true
  statusMsg.value = ''
}

async function loadData() {
  if (!fullScreenRenderer) return
  statusMsg.value = 'Loading mesh data...'

  try {
    const meshBuffer = await api.getMesh(props.sessionId, props.zone)
    const pointsArray = new Float32Array(meshBuffer)

    const renderer = fullScreenRenderer.getRenderer()
    const renderWindow = fullScreenRenderer.getRenderWindow()

    // Clear existing actors
    renderer.removeAllViewProps()

    const polydata = vtkPolyData.newInstance()
    const points = vtkPoints.newInstance()
    points.setData(pointsArray, 3)
    polydata.setPoints(points)

    // If scalar name given, fetch and apply
    if (props.scalarName) {
      statusMsg.value = 'Loading scalar data...'
      const scalarBuffer = await api.getScalar(props.sessionId, props.zone, props.scalarName)
      const scalarArray = new Float32Array(scalarBuffer)

      const scalars = vtkDataArray.newInstance({
        name: props.scalarName,
        values: scalarArray,
        numberOfComponents: 1,
      })
      polydata.getPointData().setScalars(scalars)
    }

    const ctf = vtkColorTransferFunction.newInstance()
    ctf.addRGBPoint(0.0, 0.0, 0.0, 1.0)
    ctf.addRGBPoint(0.25, 0.0, 1.0, 1.0)
    ctf.addRGBPoint(0.5, 0.0, 1.0, 0.0)
    ctf.addRGBPoint(0.75, 1.0, 1.0, 0.0)
    ctf.addRGBPoint(1.0, 1.0, 0.0, 0.0)

    const mapper = vtkMapper.newInstance()
    mapper.setInputData(polydata)
    mapper.setLookupTable(ctf)

    const actor = vtkActor.newInstance()
    actor.setMapper(mapper)

    renderer.addActor(actor)
    renderer.resetCamera()
    renderWindow.render()

    hasData.value = true
    statusMsg.value = ''
  } catch (err) {
    statusMsg.value = `Failed to load: ${err.message}`
    // Fall back to placeholder
    showPlaceholder()
  }
}
</script>

<template>
  <div class="vtk-viewer">
    <div class="viewer-label">
      <span>3D Viewer</span>
      <span v-if="path" class="viewer-path mono">{{ path }}</span>
    </div>
    <div class="viewer-container" ref="containerRef">
      <div v-if="statusMsg" class="viewer-overlay">
        {{ statusMsg }}
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
}

.viewer-path {
  font-weight: 400;
  color: var(--text-muted);
  font-size: 11px;
}

.viewer-container {
  position: relative;
  width: 100%;
  height: 400px;
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
