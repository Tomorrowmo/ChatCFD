<script setup>
import { ref, watch, onMounted, onBeforeUnmount, computed } from 'vue'

const props = defineProps({
  frameCount: { type: Number, default: 1 },
  timeLabels: { type: Array, default: () => [] },
  modelValue: { type: Number, default: 0 },  // current frame index
  bookmarkKey: { type: String, default: '' },  // per-file key for bookmark persistence
})

const emit = defineEmits(['update:modelValue'])

const PERSIST_KEY = 'chatcfd.timecontrols.v1'

const playing = ref(false)
const fps = ref(2)
const direction = ref('forward')  // 'forward' | 'reverse' | 'pingpong'
const startFrame = ref(0)
const endFrame = ref(Math.max(0, props.frameCount - 1))
const jumpTo = ref('')
const bookmarks = ref([])  // sorted array of bookmarked frame indices
let delayTimerId = null
let pingpongDir = 1  // internal: +1 / -1, only used in pingpong mode

const currentLabel = computed(() => {
  if (props.timeLabels.length > props.modelValue) {
    return props.timeLabels[props.modelValue]
  }
  return String(props.modelValue)
})

// True when a non-full play range is set
const hasRange = computed(
  () => startFrame.value > 0 || endFrame.value < props.frameCount - 1
)

// Whether timeLabels carry parseable numeric values (decides jump semantics)
const labelsAreNumeric = computed(
  () => props.timeLabels.length > 0 &&
        props.timeLabels.some(l => !isNaN(parseFloat(l)))
)

const directionIcon = computed(() => (
  { forward: '▶', reverse: '◀', pingpong: '⇄' }[direction.value]
))
const directionTitle = computed(() => (
  { forward: '正放', reverse: '倒放', pingpong: '往复' }[direction.value]
))

function setFrame(idx) {
  const clamped = Math.max(0, Math.min(idx, props.frameCount - 1))
  emit('update:modelValue', clamped)
}

function prev() { setFrame(props.modelValue - 1) }
function next() { setFrame(props.modelValue + 1) }

function togglePlay() {
  if (playing.value) stopPlay()
  else startPlay()
}

function startPlay() {
  playing.value = true
  // Snap into the active range if the cursor is outside it
  if (props.modelValue < startFrame.value || props.modelValue > endFrame.value) {
    setFrame(direction.value === 'reverse' ? endFrame.value : startFrame.value)
  }
  pingpongDir = direction.value === 'reverse' ? -1 : 1
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
  if (delayTimerId !== null) clearTimeout(delayTimerId)
  delayTimerId = setTimeout(() => {
    delayTimerId = null
    if (playing.value) advanceOnce()
  }, 1000 / fps.value)
}

function advanceOnce() {
  if (!playing.value) return
  const lo = startFrame.value
  const hi = endFrame.value
  let nextIdx
  if (direction.value === 'forward') {
    nextIdx = props.modelValue + 1
    if (nextIdx > hi) nextIdx = lo
  } else if (direction.value === 'reverse') {
    nextIdx = props.modelValue - 1
    if (nextIdx < lo) nextIdx = hi
  } else {  // pingpong
    nextIdx = props.modelValue + pingpongDir
    if (nextIdx > hi) { pingpongDir = -1; nextIdx = hi - 1 }
    else if (nextIdx < lo) { pingpongDir = 1; nextIdx = lo + 1 }
    nextIdx = Math.max(lo, Math.min(hi, nextIdx))
  }
  setFrame(nextIdx)
  // Do NOT schedule next advance — wait for parent to call frameReady()
}

function cycleDirection() {
  direction.value = (
    { forward: 'reverse', reverse: 'pingpong', pingpong: 'forward' }[direction.value]
  )
}

// In/out points — set the active play range to the current cursor
function setIn() { startFrame.value = Math.min(props.modelValue, endFrame.value) }
function setOut() { endFrame.value = Math.max(props.modelValue, startFrame.value) }
function clearRange() {
  startFrame.value = 0
  endFrame.value = props.frameCount - 1
}

function doJump() {
  const q = jumpTo.value.trim()
  if (!q) return
  // Numeric input: closest time label when labels are numeric, else frame index
  const num = parseFloat(q)
  if (!isNaN(num)) {
    if (labelsAreNumeric.value) {
      let bestIdx = -1, bestDiff = Infinity
      props.timeLabels.forEach((lbl, i) => {
        const v = parseFloat(lbl)
        if (!isNaN(v)) {
          const d = Math.abs(v - num)
          if (d < bestDiff) { bestDiff = d; bestIdx = i }
        }
      })
      if (bestIdx >= 0) { setFrame(bestIdx); jumpTo.value = ''; return }
    } else {
      setFrame(Math.round(num) - 1)  // 1-based display → 0-based index
      jumpTo.value = ''
      return
    }
  }
  // Fuzzy substring match against labels
  const idx = props.timeLabels.findIndex(l => String(l).includes(q))
  if (idx >= 0) setFrame(idx)
  jumpTo.value = ''
}

// ── Bookmarks ──────────────────────────────────────────────────────────
function bookmarkStorageKey() {
  return props.bookmarkKey ? `chatcfd.bookmarks.${props.bookmarkKey}` : ''
}

function loadBookmarks() {
  const k = bookmarkStorageKey()
  if (!k) { bookmarks.value = []; return }
  try {
    const arr = JSON.parse(localStorage.getItem(k) || '[]')
    bookmarks.value = Array.isArray(arr) ? arr.filter(b => b < props.frameCount) : []
  } catch (e) { bookmarks.value = [] }
}

function addBookmark() {
  if (!bookmarks.value.includes(props.modelValue)) {
    bookmarks.value = [...bookmarks.value, props.modelValue].sort((a, b) => a - b)
  }
}
function removeBookmark(idx) {
  bookmarks.value = bookmarks.value.filter(b => b !== idx)
}

watch(bookmarks, () => {
  const k = bookmarkStorageKey()
  if (k) {
    try { localStorage.setItem(k, JSON.stringify(bookmarks.value)) } catch (e) { /* ignore */ }
  }
}, { deep: true })

watch(() => props.bookmarkKey, loadBookmarks)

function onKeydown(e) {
  const tag = document.activeElement?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
  if (props.frameCount <= 1) return
  const step = e.shiftKey ? 10 : 1
  switch (e.key) {
    case ' ':         e.preventDefault(); togglePlay(); break
    case 'ArrowLeft': e.preventDefault(); setFrame(props.modelValue - step); break
    case 'ArrowRight':e.preventDefault(); setFrame(props.modelValue + step); break
    case 'Home':      e.preventDefault(); setFrame(0); break
    case 'End':       e.preventDefault(); setFrame(props.frameCount - 1); break
    case '[':         setIn(); break
    case ']':         setOut(); break
  }
}

// Reset range + prune stale bookmarks when a new file changes the frame count
watch(() => props.frameCount, (n) => {
  startFrame.value = 0
  endFrame.value = Math.max(0, n - 1)
  bookmarks.value = bookmarks.value.filter(b => b < n)
})

// Persist fps + direction across sessions
watch([fps, direction], () => {
  try {
    localStorage.setItem(PERSIST_KEY, JSON.stringify({
      fps: fps.value, direction: direction.value,
    }))
  } catch (e) { /* localStorage unavailable — ignore */ }
})

onMounted(() => {
  try {
    const s = JSON.parse(localStorage.getItem(PERSIST_KEY) || '{}')
    if (s.fps) fps.value = s.fps
    if (s.direction) direction.value = s.direction
  } catch (e) { /* ignore */ }
  loadBookmarks()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  stopPlay()
  window.removeEventListener('keydown', onKeydown)
})

defineExpose({ frameReady })
</script>

<template>
  <div class="time-controls" v-if="frameCount > 1">
    <button class="tc-btn" @click="prev" :disabled="playing" title="上一帧 (←)">
      <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg>
    </button>
    <button class="tc-btn play-btn" @click="togglePlay" :title="(playing ? '暂停' : '播放') + ' (Space)'">
      <svg v-if="!playing" viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
      <svg v-else viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>
    </button>
    <button class="tc-btn" @click="next" :disabled="playing" title="下一帧 (→)">
      <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg>
    </button>
    <button class="tc-btn dir-btn" @click="cycleDirection" :title="'播放方向：' + directionTitle">
      {{ directionIcon }}
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
    <span class="tc-range-group">
      <button class="tc-btn tc-mini" @click="setIn" :disabled="playing" title="设为起点 ([)">[</button>
      <button class="tc-btn tc-mini" @click="setOut" :disabled="playing" title="设为终点 (])">]</button>
      <span v-if="hasRange" class="tc-range">
        {{ startFrame + 1 }}–{{ endFrame + 1 }}
        <button class="tc-clear" @click="clearRange" :disabled="playing" title="清除区间">✕</button>
      </span>
    </span>
    <input
      type="text"
      class="tc-jump"
      v-model="jumpTo"
      @keyup.enter="doJump"
      :placeholder="labelsAreNumeric ? 't=…' : '帧#'"
      :title="labelsAreNumeric ? '输入时间值跳到最近帧' : '输入帧号跳转'"
    />
    <select v-model.number="fps" class="tc-fps-select" title="播放速度">
      <option :value="1">1 fps</option>
      <option :value="2">2 fps</option>
      <option :value="5">5 fps</option>
      <option :value="10">10 fps</option>
    </select>
    <span class="tc-bookmarks">
      <button class="tc-btn tc-mini" @click="addBookmark" title="为当前帧添加书签">★+</button>
      <button
        v-for="b in bookmarks"
        :key="b"
        class="tc-bm-chip"
        @click="setFrame(b)"
        @contextmenu.prevent="removeBookmark(b)"
        :title="`跳到帧 ${b + 1}（右键删除）`"
      >{{ b + 1 }}</button>
    </span>
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
  flex-wrap: wrap;
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

.dir-btn {
  font-size: 12px;
  line-height: 1;
  min-width: 24px;
  font-weight: 700;
}

.tc-mini {
  font-size: 12px;
  font-weight: 700;
  font-family: monospace;
  padding: 3px 6px;
}

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

.tc-range-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.tc-range {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.tc-clear {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 10px;
  padding: 0 2px;
}
.tc-clear:hover { color: var(--text-primary); }
.tc-clear:disabled { opacity: 0.35; cursor: not-allowed; }

.tc-jump {
  width: 52px;
  background: var(--bg-input, var(--bg-secondary));
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 2px 5px;
  font-size: 10px;
}

.tc-fps-select {
  background: var(--bg-input, var(--bg-secondary));
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 10px;
}

.tc-bookmarks {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-wrap: wrap;
}
.tc-bm-chip {
  background: var(--bg-secondary);
  border: 1px solid var(--accent);
  color: var(--accent);
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 10px;
  cursor: pointer;
  font-variant-numeric: tabular-nums;
}
.tc-bm-chip:hover { background: var(--accent); color: #fff; }
</style>
