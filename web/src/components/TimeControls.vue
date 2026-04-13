<script setup>
import { ref, watch, onBeforeUnmount, computed } from 'vue'

const props = defineProps({
  frameCount: { type: Number, default: 1 },
  timeLabels: { type: Array, default: () => [] },
  modelValue: { type: Number, default: 0 },  // current frame index
})

const emit = defineEmits(['update:modelValue'])

const playing = ref(false)
const fps = ref(2)
let delayTimerId = null

const currentLabel = computed(() => {
  if (props.timeLabels.length > props.modelValue) {
    return props.timeLabels[props.modelValue]
  }
  return String(props.modelValue)
})

function setFrame(idx) {
  const clamped = Math.max(0, Math.min(idx, props.frameCount - 1))
  emit('update:modelValue', clamped)
}

function prev() {
  setFrame(props.modelValue - 1)
}

function next() {
  setFrame(props.modelValue + 1)
}

function togglePlay() {
  if (playing.value) {
    stopPlay()
  } else {
    startPlay()
  }
}

function startPlay() {
  playing.value = true
  advanceOnce()
}

function stopPlay() {
  playing.value = false
  if (delayTimerId !== null) {
    clearTimeout(delayTimerId)
    delayTimerId = null
  }
}

/** Called by parent after the frame has finished loading/rendering. */
function frameReady() {
  if (!playing.value) return
  // Clear any stale timer (e.g. from overlapping loadData calls) before scheduling
  if (delayTimerId !== null) {
    clearTimeout(delayTimerId)
  }
  // Wait the configured delay, then advance to next frame
  delayTimerId = setTimeout(() => {
    delayTimerId = null
    if (playing.value) advanceOnce()
  }, 1000 / fps.value)
}

function advanceOnce() {
  if (!playing.value) return
  const nextIdx = props.modelValue + 1
  if (nextIdx >= props.frameCount) {
    setFrame(0)  // loop
  } else {
    setFrame(nextIdx)
  }
  // Do NOT schedule next advance — wait for parent to call frameReady()
}

onBeforeUnmount(() => {
  stopPlay()
})

defineExpose({ frameReady })
</script>

<template>
  <div class="time-controls" v-if="frameCount > 1">
    <button class="tc-btn" @click="prev" :disabled="playing" title="Previous frame">
      <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg>
    </button>
    <button class="tc-btn play-btn" @click="togglePlay" :title="playing ? 'Pause' : 'Play'">
      <svg v-if="!playing" viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
      <svg v-else viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>
    </button>
    <button class="tc-btn" @click="next" :disabled="playing" title="Next frame">
      <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg>
    </button>
    <input
      type="range"
      class="tc-slider"
      :min="0"
      :max="frameCount - 1"
      :value="modelValue"
      @input="setFrame(Number($event.target.value))"
    />
    <span class="tc-label">{{ modelValue + 1 }}/{{ frameCount }}</span>
    <span class="tc-time" :title="'t = ' + currentLabel">t={{ currentLabel }}</span>
    <label class="tc-fps">
      <select v-model.number="fps" class="tc-fps-select">
        <option :value="1">1 fps</option>
        <option :value="2">2 fps</option>
        <option :value="5">5 fps</option>
        <option :value="10">10 fps</option>
      </select>
    </label>
  </div>
</template>

<style scoped>
.time-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: var(--bg-tertiary);
  border-radius: 6px;
  flex-shrink: 0;
}

.tc-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  border-radius: 4px;
  padding: 3px 5px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.1s, color 0.1s;
}
.tc-btn:hover:not(:disabled) { background: var(--bg-secondary); color: var(--text-primary); }
.tc-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.play-btn { background: var(--accent); color: #fff; border-color: var(--accent); }
.play-btn:hover { filter: brightness(1.15); }

.tc-slider {
  flex: 1;
  min-width: 60px;
  max-width: 200px;
  accent-color: var(--accent);
  height: 4px;
}

.tc-label {
  font-size: 11px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.tc-time {
  font-size: 10px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tc-fps-select {
  background: var(--bg-input, var(--bg-secondary));
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 10px;
}
</style>
