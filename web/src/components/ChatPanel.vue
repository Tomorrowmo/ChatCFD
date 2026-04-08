<script setup>
import { ref, nextTick, watch, onMounted, computed } from 'vue'
import MessageBubble from './MessageBubble.vue'
import { useChatStore } from '../stores/chat.js'
import { useWebSocket } from '../composables/useWebSocket.js'

const store = useChatStore()
const { activeConversation, activeMessages, addMessage, createConversation, activeArtifacts } = store
const ws = useWebSocket()

const inputText = ref('')
const messageListRef = ref(null)
const isDragging = ref(false)

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

onMounted(() => {
  ws.connect()
})

// Detect file paths in text (e.g., "D:\path\file.cgns" or "D:/path/file.plt")
const FILE_EXTS = ['.cgns', '.cga', '.plt', '.dat', '.case', '.vtm', '.vts', '.vtu', '.vtp']
function detectFilePath(text) {
  // Match quoted paths or bare paths with known extensions
  const patterns = [
    /"([^"]+\.\w+)"/,           // "D:\path\file.cgns"
    /([A-Z]:[/\\][^\s"]+\.\w+)/i,  // D:\path\file.cgns (unquoted)
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
</script>

<template>
  <div class="chat-panel" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDrop" :class="{ 'drag-over': isDragging }">
    <div class="chat-header">
      <h2 class="truncate">{{ title }}</h2>
      <span class="badge">Phase 1</span>
    </div>

    <div class="message-list" ref="messageListRef" @scroll="checkAtBottom">
      <div v-if="messages.length === 0" class="empty-state">
        <p class="empty-title">Welcome to ChatCFD</p>
        <p class="empty-hint">Ask questions about your CFD simulation data.</p>
        <p class="empty-hint">Try: "Load the case file" or "Calculate forces on the wall zone"</p>
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
      <button class="send-btn" @click="sendMessageWithScroll" :disabled="!inputText.trim()">
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

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  gap: 8px;
  color: var(--text-muted);
}

.empty-title {
  font-size: 20px;
  font-weight: 500;
  color: var(--text-secondary);
}

.empty-hint {
  font-size: 13px;
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

.chat-panel.drag-over {
  outline: 2px dashed var(--accent);
  outline-offset: -4px;
  background: color-mix(in srgb, var(--accent) 5%, var(--bg-primary));
}
</style>
