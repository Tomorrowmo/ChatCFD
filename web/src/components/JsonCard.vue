<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  summary: { type: String, default: '' },
  data: { type: Object, default: null },
})

const formattedEntries = computed(() => {
  if (!props.data || typeof props.data !== 'object') return []
  return flattenData(props.data)
})

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

    <div class="card-data" v-if="formattedEntries.length">
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
