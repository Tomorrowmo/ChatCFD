<script setup>
import { ref, nextTick, watch, onMounted, computed } from 'vue'
import MessageBubble from './MessageBubble.vue'
import { useChatStore } from '../stores/chat.js'
import { useWebSocket } from '../composables/useWebSocket.js'
import { POST_SERVICE_URL } from '../config.js'

const store = useChatStore()
const { activeConversation, activeMessages, addMessage, createConversation, activeArtifacts } = store
const ws = useWebSocket()

const inputText = ref('')
const messageListRef = ref(null)
const isDragging = ref(false)

// Welcome screen: built-in sample cases + device detection
const samples = ref([])
const isMobile = /Mobi|Android|iPhone|iPad|iPod/i.test(
  typeof navigator !== 'undefined' ? navigator.userAgent : ''
)

// What ChatCFD can do — shown on the welcome screen
const capabilities = [
  '加载并查看 CFD 网格与物理场（压力、速度、温度…）',
  '气动力分析：升力 / 阻力 / 力矩、升阻比',
  '流场分析：涡量、压力系数 Cp、马赫数',
  '切面 / 裁剪 / 流线 / 等值面 / 矢量场 / 体渲染',
  '标量统计、数据质量检查、沿线采样、算例对比',
  '一键生成分析报告，导出 CSV',
]

// Track if agent is currently processing
const isProcessing = computed(() => {
  const msgs = activeMessages.value
  if (!msgs.length) return false
  const last = msgs[msgs.length - 1]
  return last.role === 'assistant' && last._streaming
})

// Drag & drop: extract file path and auto-fill input
function onDragOver(e) {
  e.preventDefault()
  isDragging.value = true
}
function onDragLeave() {
  isDragging.value = false
}
function onDrop(e) {
  e.preventDefault()
  isDragging.value = false
  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    const file = files[0]
    // Electron/local: file.path gives full OS path
    const filePath = file.path || file.name
    inputText.value = `"${filePath}" 分析这个文件`
  }
}

const title = computed(() => activeConversation.value?.title || 'ChatCFD')
const messages = activeMessages

onMounted(async () => {
  ws.connect()
  // Load built-in sample cases for the welcome screen
  try {
    const resp = await fetch(`${POST_SERVICE_URL}/api/samples`)
    if (resp.ok) {
      const data = await resp.json()
      samples.value = data.samples || []
    }
  } catch (e) {
    console.warn('[ChatPanel] Failed to load samples:', e)
  }
})

// Load a built-in sample case — sends a load request as if the user typed it
function loadSample(sample) {
  const text = `加载并分析示例数据 "${sample.path}"`
  addMessage('user', text)
  ws.send(text)
  isAtBottom.value = true
  nextTick(() => scrollToBottom())
}

// Detect file paths in text. Matches the four common shapes ChatCFD users type:
//   "D:\path\file.cgns"      — quoted (any style)
//   D:\path\file.cgns        — Windows absolute, drive letter
//   tests/data/ysy/ysy.cgns  — relative path with separators
//   ysy.cgns                 — bare filename
const FILE_EXTS = ['.cgns', '.cga', '.plt', '.dat', '.case', '.vtm', '.vts', '.vtu', '.vtp']
function detectFilePath(text) {
  const patterns = [
    /"([^"]+\.\w+)"/,                                       // quoted
    /([A-Z]:[/\\][^\s"]+\.\w+)/i,                           // Windows absolute
    /(?:^|\s)([\w./\\-]+\.\w+)(?=\s|$|[,;:.，；：。])/,    // relative or bare
  ]
  for (const p of patterns) {
    const m = text.match(p)
    if (m) {
      const path = m[1]
      if (FILE_EXTS.some(ext => path.toLowerCase().endsWith(ext))) return path
    }
  }
  return null
}

// Check if current conversation already has a loaded file
function hasLoadedFile() {
  return activeArtifacts.value.some(
    art => art.data && Array.isArray(art.data.zones) && art.data.zones.length > 0
  )
}

function sendMessage() {
  const text = inputText.value.trim()
  if (!text) return

  // If user sends a new file and current conversation already has a file → new conversation
  const filePath = detectFilePath(text)
  if (filePath && hasLoadedFile()) {
    const fileName = filePath.split(/[/\\]/).pop()
    createConversation(fileName)
    // No need to reconnect WebSocket — it's shared, each message carries conversation_id
  }

  addMessage('user', text)
  ws.send(text)
  inputText.value = ''
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessageWithScroll()
  }
}

// Track whether the user is pinned to the bottom. Start true, set false if
// the user scrolls up, set true again when they scroll back to the bottom.
const isAtBottom = ref(true)
const BOTTOM_THRESHOLD = 40  // px tolerance

function checkAtBottom() {
  const el = messageListRef.value
  if (!el) return
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  isAtBottom.value = distance < BOTTOM_THRESHOLD
}

function scrollToBottom() {
  if (messageListRef.value) {
    messageListRef.value.scrollTop = messageListRef.value.scrollHeight
  }
}

function scrollToBottomIfPinned() {
  if (isAtBottom.value) {
    scrollToBottom()
  }
}

// Only follow new content when user is already at the bottom
watch(
  () => messages.value,
  async () => {
    await nextTick()
    scrollToBottomIfPinned()
  },
  { deep: true }
)

watch(
  () => {
    const last = messages.value[messages.value.length - 1]
    if (!last) return 0
    const partsLen = (last.parts || []).reduce(
      (sum, p) => sum + (p.content?.length || 0) + (p.summary?.length || 0),
      0
    )
    return (last.content?.length || 0) + partsLen
  },
  async () => {
    await nextTick()
    scrollToBottomIfPinned()
  }
)

// Always scroll to bottom when switching conversations
watch(
  () => activeConversation.value?.id,
  async () => {
    await nextTick()
    isAtBottom.value = true
    scrollToBottom()
  }
)

// When user sends a message, jump back to bottom regardless
function sendMessageWithScroll() {
  sendMessage()
  isAtBottom.value = true
  nextTick(() => scrollToBottom())
}

function stopProcessing() {
  ws.cancel()
}
</script>

<template>
  <div class="chat-panel" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDrop" :class="{ 'drag-over': isDragging }">
    <div class="chat-header">
      <h2 class="truncate">{{ title }}</h2>
      <span class="badge">Phase 1</span>
    </div>

    <div class="message-list" ref="messageListRef" @scroll="checkAtBottom">
      <div v-if="messages.length === 0" class="welcome">
        <p class="welcome-title">你好，我是 ChatCFD 👋</p>
        <p class="welcome-sub">CFD 仿真数据智能分析助手。用自然语言对话，我帮你分析和可视化。</p>

        <div class="welcome-section">
          <p class="welcome-label">我能做什么</p>
          <ul class="capability-list">
            <li v-for="(cap, i) in capabilities" :key="i">{{ cap }}</li>
          </ul>
        </div>

        <div class="welcome-section">
          <p class="welcome-label">想直接体验？用示例数据试试</p>
          <div v-if="samples.length" class="sample-grid">
            <button
              v-for="s in samples"
              :key="s.id"
              class="sample-card"
              @click="loadSample(s)"
            >
              <span class="sample-name">{{ s.label }}</span>
              <span class="sample-desc">{{ s.desc }}</span>
              <span class="sample-size">{{ s.size_mb }} MB</span>
            </button>
          </div>
          <p v-else class="welcome-hint">（未找到内置示例数据）</p>
        </div>

        <div class="welcome-section">
          <p v-if="!isMobile" class="welcome-hint">
            数据就在运行 ChatCFD 的这台电脑上？直接把完整文件路径发给我，例如
            <code>D:\data\case.cgns</code>。
          </p>
          <p v-else class="welcome-hint">
            在手机上建议先用上面的示例数据体验各项能力。
          </p>
        </div>
      </div>
      <MessageBubble
        v-for="msg in messages"
        :key="msg.id"
        :role="msg.role"
        :content="msg.content"
        :parts="msg.parts || []"
        :artifacts="msg.artifacts"
      />
    </div>

    <div class="input-area">
      <textarea
        v-model="inputText"
        placeholder="Ask about your CFD data..."
        rows="2"
        @keydown="onKeydown"
      ></textarea>
      <button v-if="isProcessing" class="stop-btn" @click="stopProcessing">
        Stop
      </button>
      <button v-else class="send-btn" @click="sendMessageWithScroll" :disabled="!inputText.trim()">
        Send
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  min-width: 0;
}

.chat-header h2 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
  min-width: 0;
  flex: 1;
}

.truncate {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  flex-shrink: 0;
}

.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.welcome {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 600px;
  width: 100%;
  margin: 24px auto;
}

.welcome-title {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
}

.welcome-sub {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.welcome-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.welcome-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}

.capability-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.capability-list li {
  font-size: 13px;
  color: var(--text-secondary);
  padding-left: 18px;
  position: relative;
  line-height: 1.5;
}

.capability-list li::before {
  content: '▸';
  position: absolute;
  left: 0;
  color: var(--accent);
}

.sample-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.sample-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 200px;
  text-align: left;
  padding: 12px 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  transition: border-color 0.15s, background 0.15s;
}

.sample-card:hover {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 6%, var(--bg-secondary));
}

.sample-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.sample-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.4;
}

.sample-size {
  font-size: 11px;
  color: var(--text-muted);
}

.welcome-hint {
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.6;
}

.welcome-hint code {
  background: var(--bg-tertiary);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
}

.input-area {
  display: flex;
  gap: 10px;
  padding: 16px 20px;
  border-top: 1px solid var(--border);
  background: var(--bg-secondary);
  flex-shrink: 0;
}

.input-area textarea {
  flex: 1;
  resize: none;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  color: var(--text-primary);
  line-height: 1.4;
}

.input-area textarea::placeholder {
  color: var(--text-muted);
}

.input-area textarea:focus {
  outline: none;
  border-color: var(--accent);
}

.send-btn {
  padding: 10px 20px;
  background: var(--accent);
  color: #fff;
  border-radius: 8px;
  font-weight: 500;
  transition: background 0.15s;
  align-self: flex-end;
}

.send-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.stop-btn {
  padding: 10px 20px;
  background: #e74c3c;
  color: #fff;
  border-radius: 8px;
  font-weight: 500;
  transition: background 0.15s;
  align-self: flex-end;
}
.stop-btn:hover {
  background: #c0392b;
}

.chat-panel.drag-over {
  outline: 2px dashed var(--accent);
  outline-offset: -4px;
  background: color-mix(in srgb, var(--accent) 5%, var(--bg-primary));
}
</style>
