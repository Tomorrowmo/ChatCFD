<script setup>
import { ref, watch, computed } from 'vue'
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

const chartW = 800
const chartH = 500
const marginLeft = 60
const marginBottom = 40
const marginTop = 20
const marginRight = 20
const plotW = chartW - marginLeft - marginRight
const plotH = chartH - marginTop - marginBottom

const api = useApi()

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
      // Use demo data for mock mode
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
}

function toggleSort(colIdx) {
  if (sortCol.value === colIdx) {
    sortAsc.value = !sortAsc.value
  } else {
    sortCol.value = colIdx
    sortAsc.value = true
  }

  rows.value.sort((a, b) => {
    const va = a[colIdx]
    const vb = b[colIdx]
    const na = parseFloat(va)
    const nb = parseFloat(vb)

    let cmp
    if (!isNaN(na) && !isNaN(nb)) {
      cmp = na - nb
    } else {
      cmp = va.localeCompare(vb)
    }
    return sortAsc.value ? cmp : -cmp
  })
}

function sortIndicator(colIdx) {
  if (sortCol.value !== colIdx) return ''
  return sortAsc.value ? ' \u25B2' : ' \u25BC'
}

// --- Chart computations ---
const chartData = computed(() => {
  if (!chartX.value || !chartY.value) return null
  const xi = headers.value.indexOf(chartX.value)
  const yi = headers.value.indexOf(chartY.value)
  if (xi < 0 || yi < 0) return null

  const points = []
  for (const row of rows.value) {
    const x = parseFloat(row[xi])
    const y = parseFloat(row[yi])
    if (!isNaN(x) && !isNaN(y)) {
      points.push({ x, y })
    }
  }
  if (points.length === 0) return null

  // Sort by x for connected line
  points.sort((a, b) => a.x - b.x)

  const xMin = Math.min(...points.map((p) => p.x))
  const xMax = Math.max(...points.map((p) => p.x))
  const yMin = Math.min(...points.map((p) => p.y))
  const yMax = Math.max(...points.map((p) => p.y))

  // Add padding to range
  const xRange = xMax - xMin || 1
  const yRange = yMax - yMin || 1
  const xLo = xMin - xRange * 0.05
  const xHi = xMax + xRange * 0.05
  const yLo = yMin - yRange * 0.05
  const yHi = yMax + yRange * 0.05

  function scaleX(v) {
    return marginLeft + ((v - xLo) / (xHi - xLo)) * plotW
  }
  function scaleY(v) {
    return marginTop + plotH - ((v - yLo) / (yHi - yLo)) * plotH
  }

  const scaled = points.map((p) => ({ sx: scaleX(p.x), sy: scaleY(p.y), ...p }))
  const polyline = scaled.map((p) => `${p.sx},${p.sy}`).join(' ')

  // Ticks
  const xTicks = []
  const yTicks = []
  for (let i = 0; i < 5; i++) {
    const xv = xLo + ((xHi - xLo) * i) / 4
    xTicks.push({ v: formatTick(xv), px: scaleX(xv) })
    const yv = yLo + ((yHi - yLo) * i) / 4
    yTicks.push({ v: formatTick(yv), px: scaleY(yv) })
  }

  return { scaled, polyline, xTicks, yTicks }
})

function formatTick(v) {
  if (Math.abs(v) >= 1e6 || (Math.abs(v) < 0.01 && v !== 0)) {
    return v.toExponential(1)
  }
  // Up to 3 decimal places, strip trailing zeros
  return parseFloat(v.toFixed(3)).toString()
}
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
    </div>

    <div v-if="loading" class="table-status">Loading...</div>
    <div v-else-if="error" class="table-status error">{{ error }}</div>

    <div v-else-if="mode === 'table'" class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th
              v-for="(h, idx) in headers"
              :key="idx"
              @click="toggleSort(idx)"
              class="sortable"
            >
              {{ h }}{{ sortIndicator(idx) }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, ridx) in rows" :key="ridx">
            <td v-for="(cell, cidx) in row" :key="cidx" class="mono">
              {{ cell }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else-if="mode === 'chart'" class="chart-container">
      <div v-if="!chartData" class="table-status">
        Select numeric columns for X and Y axes
      </div>
      <svg v-else class="chart-svg" :viewBox="`0 0 ${chartW} ${chartH}`" preserveAspectRatio="xMidYMid meet">
        <!-- X axis -->
        <line
          :x1="marginLeft" :y1="marginTop + plotH"
          :x2="marginLeft + plotW" :y2="marginTop + plotH"
          stroke="var(--text-muted)" stroke-width="1"
        />
        <!-- Y axis -->
        <line
          :x1="marginLeft" :y1="marginTop"
          :x2="marginLeft" :y2="marginTop + plotH"
          stroke="var(--text-muted)" stroke-width="1"
        />

        <!-- X tick labels -->
        <template v-for="(t, i) in chartData.xTicks" :key="'xt' + i">
          <line :x1="t.px" :y1="marginTop + plotH" :x2="t.px" :y2="marginTop + plotH + 5"
                stroke="var(--text-muted)" stroke-width="1"/>
          <text :x="t.px" :y="marginTop + plotH + 20"
                text-anchor="middle" fill="var(--text-secondary)" font-size="11">{{ t.v }}</text>
        </template>

        <!-- Y tick labels -->
        <template v-for="(t, i) in chartData.yTicks" :key="'yt' + i">
          <line :x1="marginLeft - 5" :y1="t.px" :x2="marginLeft" :y2="t.px"
                stroke="var(--text-muted)" stroke-width="1"/>
          <text :x="marginLeft - 8" :y="t.px + 4"
                text-anchor="end" fill="var(--text-secondary)" font-size="11">{{ t.v }}</text>
        </template>

        <!-- Axis labels -->
        <text :x="marginLeft + plotW / 2" :y="chartH - 2"
              text-anchor="middle" fill="var(--text-secondary)" font-size="12" font-weight="500">{{ chartX }}</text>
        <text :x="14" :y="marginTop + plotH / 2"
              text-anchor="middle" fill="var(--text-secondary)" font-size="12" font-weight="500"
              :transform="`rotate(-90, 14, ${marginTop + plotH / 2})`">{{ chartY }}</text>

        <!-- Line connecting points -->
        <polyline
          :points="chartData.polyline"
          fill="none" stroke="var(--accent)" stroke-width="1.5"
          stroke-linejoin="round" stroke-linecap="round"
        />

        <!-- Data points -->
        <circle
          v-for="(p, i) in chartData.scaled" :key="'p' + i"
          :cx="p.sx" :cy="p.sy" r="3"
          fill="var(--accent)" stroke="#fff" stroke-width="1"
        />
      </svg>
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

.mode-bar button:hover {
  background: var(--bg-hover);
}

.mode-bar button.active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.mode-bar label {
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: 6px;
}

.mode-bar select {
  padding: 3px 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 12px;
  max-width: 140px;
}

.table-status {
  padding: 40px;
  text-align: center;
  color: var(--text-muted);
}

.table-status.error {
  color: var(--error);
}

.table-scroll {
  overflow-x: auto;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.data-table th {
  position: sticky;
  top: 0;
  background: var(--bg-input);
  padding: 10px 14px;
  text-align: left;
  font-weight: 600;
  color: var(--text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.data-table th.sortable {
  cursor: pointer;
  user-select: none;
}

.data-table th.sortable:hover {
  color: var(--text-primary);
}

.data-table td {
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  color: var(--text-primary);
}

.data-table tbody tr:hover {
  background: var(--bg-hover);
}

.chart-container {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
}

.chart-svg {
  width: 100%;
  height: 100%;
}
</style>
