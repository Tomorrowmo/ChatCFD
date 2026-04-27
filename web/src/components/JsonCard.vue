<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  summary: { type: String, default: '' },
  data: { type: Object, default: null },
})

// Detect "row-table" shape: all values are plain objects with the same keys,
// and those keys map to primitives. E.g. {Pressure: {min, max, mean, std}, ...}
const tableView = computed(() => {
  const d = props.data
  if (!d || typeof d !== 'object' || Array.isArray(d)) return null
  const rows = Object.entries(d)
  if (rows.length === 0) return null

  let columns = null
  for (const [, v] of rows) {
    if (!v || typeof v !== 'object' || Array.isArray(v)) return null
    const keys = Object.keys(v)
    if (keys.length === 0) return null
    if (columns === null) {
      columns = keys
    } else if (keys.length !== columns.length || keys.some((k, i) => k !== columns[i])) {
      return null
    }
    // Require all column values to be primitives (not nested)
    for (const k of columns) {
      const cell = v[k]
      if (cell !== null && typeof cell === 'object') return null
    }
  }
  return { columns, rows }
})

const formattedEntries = computed(() => {
  if (!props.data || typeof props.data !== 'object') return []
  return flattenData(props.data)
})

function formatCell(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'number') {
    if (!isFinite(v)) return String(v)
    const abs = Math.abs(v)
    if (abs !== 0 && (abs < 1e-3 || abs >= 1e6)) return v.toExponential(4)
    return Number(v.toPrecision(6)).toString()
  }
  return String(v)
}

function flattenData(obj, prefix = '') {
  const entries = []
  for (const [key, value] of Object.entries(obj)) {
    const label = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      entries.push(...flattenData(value, label))
    } else if (Array.isArray(value)) {
      entries.push({ key: label, value: value.join(', ') })
    } else {
      entries.push({ key: label, value: String(value) })
    }
  }
  return entries
}
</script>

<template>
  <div class="json-card">
    <div class="card-title" v-if="title">{{ title }}</div>
    <div class="card-summary" v-if="summary">{{ summary }}</div>

    <!-- Table view: homogeneous row-of-objects shape (e.g. statistics) -->
    <div class="card-table" v-if="tableView">
      <table>
        <thead>
          <tr>
            <th class="row-name">name</th>
            <th v-for="c in tableView.columns" :key="c">{{ c }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="[name, row] in tableView.rows" :key="name">
            <td class="row-name">{{ name }}</td>
            <td v-for="c in tableView.columns" :key="c" class="mono">{{ formatCell(row[c]) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Fallback: flattened key-value list -->
    <div class="card-data" v-else-if="formattedEntries.length">
      <div class="data-row" v-for="entry in formattedEntries" :key="entry.key">
        <span class="data-key">{{ entry.key }}</span>
        <span class="data-value mono">{{ entry.value }}</span>
      </div>
    </div>

    <div v-else-if="data" class="card-raw mono">
      <pre>{{ JSON.stringify(data, null, 2) }}</pre>
    </div>
  </div>
</template>

<style scoped>
.json-card {
  background: var(--bg-tertiary);
  border-radius: 10px;
  padding: 20px;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.card-summary {
  font-size: 14px;
  color: var(--accent);
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

.card-data {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.data-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 4px 0;
}

.data-key {
  color: var(--text-secondary);
  font-size: 13px;
}

.data-value {
  color: var(--text-primary);
  font-weight: 500;
  text-align: right;
}

.card-table {
  overflow-x: auto;
}

.card-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.card-table th,
.card-table td {
  padding: 6px 10px;
  text-align: right;
  border-bottom: 1px solid var(--border);
}

.card-table th {
  color: var(--text-secondary);
  font-weight: 600;
  background: var(--bg-secondary, transparent);
  text-transform: lowercase;
}

.card-table td {
  color: var(--text-primary);
}

.card-table .row-name {
  text-align: left;
  color: var(--text-secondary);
  font-weight: 500;
}

.card-table tbody tr:hover {
  background: var(--bg-secondary, rgba(127, 127, 127, 0.06));
}

.card-raw {
  max-height: 400px;
  overflow: auto;
}

.card-raw pre {
  white-space: pre-wrap;
  color: var(--text-secondary);
  font-size: 12px;
  margin: 0;
}
</style>
