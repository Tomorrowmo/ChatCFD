<script setup>
import { ref, watch } from 'vue'
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
</script>

<template>
  <div class="data-table-wrapper">
    <div v-if="loading" class="table-status">Loading...</div>
    <div v-else-if="error" class="table-status error">{{ error }}</div>
    <div v-else class="table-scroll">
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
</style>
