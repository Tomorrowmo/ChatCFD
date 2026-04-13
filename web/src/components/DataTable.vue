<script setup>
import { ref, watch, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useApi } from '../composables/useApi.js'

const props = defineProps({
  path: { type: String, required: true },
})

const headers = ref([])
const rows = ref([])
const loading = ref(false)
const error = ref(null)
const sortCol = ref(-1)
const sortAsc = ref(true)

const mode = ref('table')
const chartX = ref('')
const chartY = ref('')

const api = useApi()

// --- Virtual scroll state ---
const ROW_HEIGHT = 33
const BUFFER = 10
const scrollRef = ref(null)
const scrollTop = ref(0)
const viewportH = ref(400)

const totalHeight = computed(() => rows.value.length * ROW_HEIGHT)

const visibleRange = computed(() => {
  const start = Math.max(0, Math.floor(scrollTop.value / ROW_HEIGHT) - BUFFER)
  const visibleCount = Math.ceil(viewportH.value / ROW_HEIGHT) + 2 * BUFFER
  const end = Math.min(rows.value.length, start + visibleCount)
  return { start, end }
})

const visibleRows = computed(() => {
  const { start, end } = visibleRange.value
  return rows.value.slice(start, end).map((row, i) => ({ row, idx: start + i }))
})

const offsetY = computed(() => visibleRange.value.start * ROW_HEIGHT)

function onScroll(e) {
  scrollTop.value = e.target.scrollTop
}

let resizeObserver = null
onMounted(() => {
  if (scrollRef.value) {
    viewportH.value = scrollRef.value.clientHeight
    resizeObserver = new ResizeObserver(([entry]) => {
      viewportH.value = entry.contentRect.height
    })
    resizeObserver.observe(scrollRef.value)
  }
})
onBeforeUnmount(() => { resizeObserver?.disconnect() })

watch(
  () => props.path,
  async (newPath) => {
    if (!newPath) return
    loading.value = true
    error.value = null
    try {
      const blob = await api.downloadFile(newPath)
      const text = await blob.text()
      parseCSV(text)
    } catch (err) {
      error.value = `Failed to load CSV: ${err.message}`
      parseCSV(
        'Zone,Pressure_avg,Pressure_max,Velocity_avg\ninlet,101325.0,101400.5,12.34\noutlet,100800.2,100950.0,15.67\nwall,101100.8,101325.0,0.00'
      )
      error.value = null
    } finally {
      loading.value = false
    }
  },
  { immediate: true }
)

watch(headers, (h) => {
  if (h.length >= 2) {
    chartX.value = h[0]
    chartY.value = h.length > 1 ? h[1] : h[0]
  }
})

function parseCSV(text) {
  const lines = text.trim().split('\n')
  if (lines.length < 1) return
  headers.value = lines[0].split(',').map((h) => h.trim())
  rows.value = lines.slice(1).map((line) => line.split(',').map((c) => c.trim()))
  scrollTop.value = 0
  if (scrollRef.value) scrollRef.value.scrollTop = 0
}

function toggleSort(colIdx) {
  if (sortCol.value === colIdx) {
    sortAsc.value = !sortAsc.value
  } else {
    sortCol.value = colIdx
    sortAsc.value = true
  }
  rows.value.sort((a, b) => {
    const va = a[colIdx], vb = b[colIdx]
    const na = parseFloat(va), nb = parseFloat(vb)
    const cmp = (!isNaN(na) && !isNaN(nb)) ? na - nb : va.localeCompare(vb)
    return sortAsc.value ? cmp : -cmp
  })
}

function sortIndicator(colIdx) {
  if (sortCol.value !== colIdx) return ''
  return sortAsc.value ? ' \u25B2' : ' \u25BC'
}

// ─── Canvas chart ───
const canvasRef = ref(null)
const tooltipRef = ref(null)
const tooltip = ref({ show: false, x: 0, y: 0, xVal: '', yVal: '' })
let chartState = null      // cached geometry for hover lookup
let chartResizeObs = null

const CHART_COLORS = {
  line: '#4f8ff7',
  dot: '#4f8ff7',
  gradientTop: 'rgba(79,143,247,0.25)',
  gradientBot: 'rgba(79,143,247,0.02)',
  grid: 'rgba(128,128,128,0.15)',
  axis: 'rgba(128,128,128,0.5)',
  tick: 'rgba(180,180,180,0.9)',
  crosshair: 'rgba(79,143,247,0.4)',
}

// LTTB downsampling: keeps visual shape with far fewer points
function lttb(data, threshold) {
  const len = data.length
  if (len <= threshold) return data
  const result = [data[0]]
  const bucketSize = (len - 2) / (threshold - 2)
  let prev = 0
  for (let i = 0; i < threshold - 2; i++) {
    const rStart = Math.floor((i + 1) * bucketSize) + 1
    const rEnd = Math.min(Math.floor((i + 2) * bucketSize) + 1, len)
    // Average of next bucket
    const nStart = Math.floor((i + 2) * bucketSize) + 1
    const nEnd = Math.min(Math.floor((i + 3) * bucketSize) + 1, len)
    let avgX = 0, avgY = 0, cnt = 0
    for (let j = nStart; j < nEnd; j++) { avgX += data[j].x; avgY += data[j].y; cnt++ }
    if (cnt > 0) { avgX /= cnt; avgY /= cnt }
    else { avgX = data[len - 1].x; avgY = data[len - 1].y }
    // Largest triangle in current bucket
    let maxArea = -1, maxIdx = rStart
    const pA = data[prev]
    for (let j = rStart; j < rEnd; j++) {
      const area = Math.abs((pA.x - avgX) * (data[j].y - pA.y) - (pA.x - data[j].x) * (avgY - pA.y))
      if (area > maxArea) { maxArea = area; maxIdx = j }
    }
    result.push(data[maxIdx])
    prev = maxIdx
  }
  result.push(data[len - 1])
  return result
}

function niceTickValues(lo, hi, maxTicks = 6) {
  const range = hi - lo
  if (range === 0) return [lo]
  const rough = range / (maxTicks - 1)
  const mag = Math.pow(10, Math.floor(Math.log10(rough)))
  const norm = rough / mag
  let step
  if (norm <= 1.5) step = 1 * mag
  else if (norm <= 3) step = 2 * mag
  else if (norm <= 7) step = 5 * mag
  else step = 10 * mag
  const start = Math.ceil(lo / step) * step
  const ticks = []
  for (let v = start; v <= hi + step * 0.01; v += step) ticks.push(v)
  return ticks
}

function formatTick(v) {
  if (v === 0) return '0'
  if (Math.abs(v) >= 1e6 || (Math.abs(v) < 0.01 && v !== 0)) return v.toExponential(1)
  return parseFloat(v.toPrecision(6)).toString()
}

function drawChart() {
  const canvas = canvasRef.value
  if (!canvas) return
  const rect = canvas.parentElement.getBoundingClientRect()
  const W = Math.floor(rect.width) || 800
  const H = Math.floor(rect.height) || 500
  const dpr = window.devicePixelRatio || 1
  canvas.width = W * dpr
  canvas.height = H * dpr
  canvas.style.width = W + 'px'
  canvas.style.height = H + 'px'
  const ctx = canvas.getContext('2d')
  ctx.scale(dpr, dpr)

  const xi = headers.value.indexOf(chartX.value)
  const yi = headers.value.indexOf(chartY.value)
  if (xi < 0 || yi < 0) {
    chartState = null
    ctx.fillStyle = 'rgba(128,128,128,0.5)'
    ctx.font = '14px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('Select numeric columns for X and Y axes', W / 2, H / 2)
    return
  }

  // Parse points
  const allPoints = []
  for (const row of rows.value) {
    const x = parseFloat(row[xi]), y = parseFloat(row[yi])
    if (!isNaN(x) && !isNaN(y)) allPoints.push({ x, y })
  }
  if (allPoints.length === 0) {
    chartState = null
    ctx.fillStyle = 'rgba(128,128,128,0.5)'
    ctx.font = '14px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('No numeric data for selected columns', W / 2, H / 2)
    return
  }
  allPoints.sort((a, b) => a.x - b.x)

  // Compute range (safe for huge arrays — no spread operator)
  let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity
  for (const p of allPoints) {
    if (p.x < xMin) xMin = p.x; if (p.x > xMax) xMax = p.x
    if (p.y < yMin) yMin = p.y; if (p.y > yMax) yMax = p.y
  }
  const xPad = (xMax - xMin || 1) * 0.05
  const yPad = (yMax - yMin || 1) * 0.05
  const xLo = xMin - xPad, xHi = xMax + xPad
  const yLo = yMin - yPad, yHi = yMax + yPad

  // Layout
  const ml = 65, mr = 20, mt = 20, mb = 50
  const pw = W - ml - mr, ph = H - mt - mb
  const sx = v => ml + (v - xLo) / (xHi - xLo) * pw
  const sy = v => mt + ph - (v - yLo) / (yHi - yLo) * ph

  // Downsample for rendering
  const maxPts = Math.min(2000, pw * 2)
  const displayPts = lttb(allPoints, maxPts)

  // Cache for hover
  chartState = { allPoints, sx, sy, xLo, xHi, yLo, yHi, ml, mr, mt, mb, pw, ph, W, H }

  // Clear
  ctx.clearRect(0, 0, W, H)

  // Grid lines
  const xTicks = niceTickValues(xLo, xHi)
  const yTicks = niceTickValues(yLo, yHi)
  ctx.strokeStyle = CHART_COLORS.grid
  ctx.lineWidth = 1
  ctx.setLineDash([4, 4])
  for (const v of yTicks) {
    const py = sy(v)
    ctx.beginPath(); ctx.moveTo(ml, py); ctx.lineTo(ml + pw, py); ctx.stroke()
  }
  for (const v of xTicks) {
    const px = sx(v)
    ctx.beginPath(); ctx.moveTo(px, mt); ctx.lineTo(px, mt + ph); ctx.stroke()
  }
  ctx.setLineDash([])

  // Axes
  ctx.strokeStyle = CHART_COLORS.axis
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(ml, mt); ctx.lineTo(ml, mt + ph); ctx.lineTo(ml + pw, mt + ph)
  ctx.stroke()

  // Tick labels
  ctx.fillStyle = CHART_COLORS.tick
  ctx.font = '11px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  for (const v of xTicks) {
    const px = sx(v)
    ctx.beginPath(); ctx.moveTo(px, mt + ph); ctx.lineTo(px, mt + ph + 5); ctx.stroke()
    ctx.fillText(formatTick(v), px, mt + ph + 8)
  }
  ctx.textAlign = 'right'
  ctx.textBaseline = 'middle'
  for (const v of yTicks) {
    const py = sy(v)
    ctx.beginPath(); ctx.moveTo(ml - 5, py); ctx.lineTo(ml, py); ctx.stroke()
    ctx.fillText(formatTick(v), ml - 8, py)
  }

  // Axis labels
  ctx.fillStyle = 'rgba(160,160,170,0.9)'
  ctx.font = '12px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillText(chartX.value, ml + pw / 2, H - 14)
  ctx.save()
  ctx.translate(16, mt + ph / 2)
  ctx.rotate(-Math.PI / 2)
  ctx.textBaseline = 'middle'
  ctx.fillText(chartY.value, 0, 0)
  ctx.restore()

  // Area fill gradient
  const grad = ctx.createLinearGradient(0, mt, 0, mt + ph)
  grad.addColorStop(0, CHART_COLORS.gradientTop)
  grad.addColorStop(1, CHART_COLORS.gradientBot)
  ctx.fillStyle = grad
  ctx.beginPath()
  ctx.moveTo(sx(displayPts[0].x), mt + ph) // bottom-left
  for (const p of displayPts) ctx.lineTo(sx(p.x), sy(p.y))
  ctx.lineTo(sx(displayPts[displayPts.length - 1].x), mt + ph) // bottom-right
  ctx.closePath()
  ctx.fill()

  // Line
  ctx.strokeStyle = CHART_COLORS.line
  ctx.lineWidth = 1.8
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  ctx.beginPath()
  for (let i = 0; i < displayPts.length; i++) {
    const px = sx(displayPts[i].x), py = sy(displayPts[i].y)
    if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
  }
  ctx.stroke()

  // Dots only if few points
  if (displayPts.length <= 200) {
    ctx.fillStyle = CHART_COLORS.dot
    for (const p of displayPts) {
      const px = sx(p.x), py = sy(p.y)
      ctx.beginPath(); ctx.arc(px, py, 2.5, 0, Math.PI * 2); ctx.fill()
    }
  }

  // Point count badge
  if (allPoints.length > maxPts) {
    ctx.fillStyle = 'rgba(128,128,128,0.4)'
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'right'
    ctx.textBaseline = 'top'
    ctx.fillText(`${allPoints.length.toLocaleString()} pts (LTTB → ${displayPts.length})`, W - mr, 6)
  }
}

function onChartHover(e) {
  if (!chartState) { tooltip.value.show = false; return }
  const canvas = canvasRef.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top
  const { allPoints, sx, sy, ml, mt, pw, ph } = chartState

  // Outside plot area?
  if (mx < ml || mx > ml + pw || my < mt || my > mt + ph) {
    tooltip.value.show = false
    drawChart()  // redraw to clear crosshair
    return
  }

  // Binary search for closest x
  const xVal = chartState.xLo + (mx - ml) / pw * (chartState.xHi - chartState.xLo)
  let lo = 0, hi = allPoints.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (allPoints[mid].x < xVal) lo = mid + 1; else hi = mid
  }
  // Check neighbors
  let best = lo
  if (lo > 0 && Math.abs(allPoints[lo - 1].x - xVal) < Math.abs(allPoints[lo].x - xVal)) best = lo - 1

  const pt = allPoints[best]
  const px = sx(pt.x), py = sy(pt.y)

  // Redraw base chart + crosshair + dot
  drawChart()
  const ctx = canvas.getContext('2d')
  const dpr = window.devicePixelRatio || 1
  ctx.save()
  ctx.scale(dpr, dpr)

  // Crosshair
  ctx.strokeStyle = CHART_COLORS.crosshair
  ctx.lineWidth = 1
  ctx.setLineDash([3, 3])
  ctx.beginPath(); ctx.moveTo(px, mt); ctx.lineTo(px, mt + ph); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(ml, py); ctx.lineTo(ml + pw, py); ctx.stroke()
  ctx.setLineDash([])

  // Highlight dot
  ctx.fillStyle = '#fff'
  ctx.beginPath(); ctx.arc(px, py, 5, 0, Math.PI * 2); ctx.fill()
  ctx.fillStyle = CHART_COLORS.dot
  ctx.beginPath(); ctx.arc(px, py, 3.5, 0, Math.PI * 2); ctx.fill()

  ctx.restore()

  // Position tooltip
  tooltip.value = {
    show: true,
    x: Math.min(px + 12, chartState.W - 140),
    y: Math.max(py - 40, 4),
    xVal: `${chartX.value}: ${formatTick(pt.x)}`,
    yVal: `${chartY.value}: ${formatTick(pt.y)}`,
  }
}

function onChartLeave() {
  tooltip.value.show = false
  drawChart()
}

// Redraw on data/column change
watch([chartX, chartY, rows, mode], () => {
  if (mode.value === 'chart') nextTick(drawChart)
})

// Handle resize
onMounted(() => {
  const container = canvasRef.value?.parentElement
  if (container) {
    chartResizeObs = new ResizeObserver(() => {
      if (mode.value === 'chart') drawChart()
    })
    chartResizeObs.observe(container)
  }
})
onBeforeUnmount(() => { chartResizeObs?.disconnect() })
</script>

<template>
  <div class="data-table-wrapper">
    <div class="mode-bar">
      <button :class="{ active: mode === 'table' }" @click="mode = 'table'">Table</button>
      <button :class="{ active: mode === 'chart' }" @click="mode = 'chart'">Chart</button>
      <template v-if="mode === 'chart'">
        <label>X: <select v-model="chartX">
          <option v-for="h in headers" :key="h" :value="h">{{ h }}</option>
        </select></label>
        <label>Y: <select v-model="chartY">
          <option v-for="h in headers" :key="h" :value="h">{{ h }}</option>
        </select></label>
      </template>
      <span v-if="mode === 'table' && rows.length" class="row-count">{{ rows.length.toLocaleString() }} rows</span>
    </div>

    <div v-if="loading" class="table-status">Loading...</div>
    <div v-else-if="error" class="table-status error">{{ error }}</div>

    <div v-else-if="mode === 'table'" ref="scrollRef" class="table-scroll" @scroll="onScroll">
      <table class="data-table data-table-header">
        <thead>
          <tr>
            <th v-for="(h, idx) in headers" :key="idx" @click="toggleSort(idx)" class="sortable">
              {{ h }}{{ sortIndicator(idx) }}
            </th>
          </tr>
        </thead>
      </table>
      <div :style="{ height: totalHeight + 'px', position: 'relative' }">
        <table class="data-table data-table-body" :style="{ transform: `translateY(${offsetY}px)` }">
          <tbody>
            <tr v-for="item in visibleRows" :key="item.idx">
              <td v-for="(cell, cidx) in item.row" :key="cidx" class="mono">{{ cell }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-else-if="mode === 'chart'" class="chart-container">
      <canvas
        ref="canvasRef"
        class="chart-canvas"
        @mousemove="onChartHover"
        @mouseleave="onChartLeave"
      />
      <div
        v-if="tooltip.show"
        class="chart-tooltip"
        :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }"
      >
        <div class="tt-row">{{ tooltip.xVal }}</div>
        <div class="tt-row tt-y">{{ tooltip.yVal }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.data-table-wrapper {
  background: var(--bg-tertiary);
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.mode-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  flex-wrap: wrap;
}
.mode-bar button {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
}
.mode-bar button:hover { background: var(--bg-hover); }
.mode-bar button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.mode-bar label {
  font-size: 12px; color: var(--text-secondary);
  display: flex; align-items: center; gap: 4px; margin-left: 6px;
}
.mode-bar select {
  padding: 3px 6px; border: 1px solid var(--border); border-radius: 4px;
  background: var(--bg-input); color: var(--text-primary); font-size: 12px; max-width: 140px;
}
.row-count {
  margin-left: auto; font-size: 11px; color: var(--text-muted); font-variant-numeric: tabular-nums;
}

.table-status { padding: 40px; text-align: center; color: var(--text-muted); }
.table-status.error { color: var(--error); }

.table-scroll { overflow-x: auto; overflow-y: auto; flex: 1; min-height: 0; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
.data-table-header { position: sticky; top: 0; z-index: 2; }
.data-table-body { position: absolute; top: 0; left: 0; width: 100%; }
.data-table th {
  background: var(--bg-input); padding: 10px 14px; text-align: left;
  font-weight: 600; color: var(--text-secondary); font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.03em;
  border-bottom: 1px solid var(--border); white-space: nowrap;
}
.data-table th.sortable { cursor: pointer; user-select: none; }
.data-table th.sortable:hover { color: var(--text-primary); }
.data-table td {
  padding: 8px 14px; border-bottom: 1px solid var(--border); color: var(--text-primary);
  height: 33px; box-sizing: border-box; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.data-table tbody tr:hover { background: var(--bg-hover); }

/* ── Chart ── */
.chart-container {
  flex: 1; min-height: 0; position: relative; padding: 8px;
}
.chart-canvas {
  display: block; width: 100%; height: 100%; cursor: crosshair;
}
.chart-tooltip {
  position: absolute;
  pointer-events: none;
  background: rgba(30, 32, 38, 0.92);
  backdrop-filter: blur(6px);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 11px;
  color: #e0e0e4;
  white-space: nowrap;
  z-index: 10;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}
.tt-row { line-height: 1.5; }
.tt-y { color: #6db3f8; font-weight: 600; }
</style>
