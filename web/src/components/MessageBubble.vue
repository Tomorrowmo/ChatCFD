<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { useChatStore } from '../stores/chat.js'

const props = defineProps({
  role: { type: String, required: true },
  content: { type: String, required: true },
  parts: { type: Array, default: () => [] },
  artifacts: { type: Array, default: () => [] },
})

const { activeArtifacts, setActiveArtifact } = useChatStore()

function onArtifactClick(artifactRef) {
  const idx = activeArtifacts.value.findIndex((a) => a.id === artifactRef.id)
  if (idx >= 0) {
    setActiveArtifact(idx)
  }
}

// Tick every 100ms to update elapsed time counters on running tool parts
const tick = ref(0)
let timerId = null
onMounted(() => {
  timerId = setInterval(() => {
    tick.value++
  }, 100)
})
onBeforeUnmount(() => {
  if (timerId) clearInterval(timerId)
})

function formatElapsed(part) {
  // tick dependency to re-render
  // eslint-disable-next-line no-unused-vars
  const _ = tick.value
  const end = part.finished_at || Date.now()
  const ms = end - part.started_at
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatArgsHint(tool, args) {
  if (!args) return ''
  if (tool === 'loadFile' && args.file_path) {
    return args.file_path.split(/[\\/]/).pop()
  }
  if (tool === 'calculate' && args.method) {
    return args.zone_name ? `${args.method} / ${args.zone_name}` : args.method
  }
  if (tool === 'exportData' && args.zone) return args.zone
  if (tool === 'listFiles' && args.directory) return args.directory
  return ''
}

// Use parts if available, otherwise fall back to plain content
const hasParts = computed(() => props.parts && props.parts.length > 0)
</script>

<template>
  <div class="bubble-row" :class="role">
    <div class="bubble" :class="role">
      <template v-if="hasParts">
        <template v-for="(part, i) in parts" :key="i">
          <div v-if="part.type === 'text'" class="bubble-text">{{ part.content }}</div>
          <div v-else-if="part.type === 'tool'" class="tool-part" :class="part.status">
            <div class="tool-header">
              <span class="tool-icon">
                <span v-if="part.status === 'running'" class="spinner"></span>
                <span v-else class="check">✓</span>
              </span>
              <span class="tool-name">{{ part.tool }}</span>
              <span class="tool-args mono">{{ formatArgsHint(part.tool, part.args) }}</span>
              <span class="tool-elapsed mono">{{ formatElapsed(part) }}</span>
            </div>
            <div v-if="part.status === 'done' && part.summary" class="tool-summary">
              {{ part.summary }}
            </div>
          </div>
        </template>
      </template>
      <div v-else class="bubble-text">{{ content }}</div>

      <div v-if="artifacts.length" class="artifact-links">
        <button
          v-for="art in artifacts"
          :key="art.id"
          class="artifact-link"
          @click="onArtifactClick(art)"
        >
          <span class="artifact-icon">&#x1F4CE;</span>
          {{ art.title }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bubble-row {
  display: flex;
}

.bubble-row.user {
  justify-content: flex-end;
}

.bubble-row.assistant {
  justify-content: flex-start;
}

.bubble {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  line-height: 1.5;
  word-wrap: break-word;
}

.bubble.user {
  background: var(--bg-user-msg);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.bubble.assistant {
  background: var(--bg-ai-msg);
  color: var(--text-primary);
  border-bottom-left-radius: 4px;
}

.bubble-text {
  white-space: pre-wrap;
}

.tool-part {
  margin: 8px 0;
  padding: 8px 10px;
  border-left: 2px solid var(--accent);
  background: rgba(255, 255, 255, 0.04);
  border-radius: 4px;
  font-size: 12px;
}

.tool-part.done {
  border-left-color: #4ade80;
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
}

.tool-icon {
  display: inline-flex;
  width: 14px;
  height: 14px;
  align-items: center;
  justify-content: center;
}

.spinner {
  width: 11px;
  height: 11px;
  border: 2px solid rgba(255, 255, 255, 0.2);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.check {
  color: #4ade80;
  font-weight: bold;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.tool-name {
  font-weight: 600;
  color: var(--text-primary);
}

.tool-args {
  color: var(--text-muted);
  font-size: 11px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-elapsed {
  color: var(--text-muted);
  font-size: 11px;
}

.tool-summary {
  margin-top: 4px;
  padding-left: 22px;
  color: var(--text-secondary);
  font-size: 11px;
}

.artifact-links {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.artifact-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--accent);
  font-size: 12px;
  transition: background 0.15s;
}

.artifact-link:hover {
  background: rgba(255, 255, 255, 0.15);
}

.artifact-icon {
  font-size: 13px;
}
</style>
