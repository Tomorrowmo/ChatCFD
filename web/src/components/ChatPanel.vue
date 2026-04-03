<script setup>
import { ref, nextTick, watch, onMounted } from 'vue'
import MessageBubble from './MessageBubble.vue'
import { useChatStore } from '../stores/chat.js'
import { useWebSocket } from '../composables/useWebSocket.js'

const { state, addMessage } = useChatStore()
const ws = useWebSocket()

const inputText = ref('')
const messageListRef = ref(null)

onMounted(() => {
  ws.connect()
})

function sendMessage() {
  const text = inputText.value.trim()
  if (!text) return

  addMessage('user', text)
  ws.send(text)
  inputText.value = ''
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

// Auto-scroll to bottom on new messages
watch(
  () => state.messages.length,
  async () => {
    await nextTick()
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight
    }
  }
)
</script>

<template>
  <div class="chat-panel">
    <div class="chat-header">
      <h2>ChatCFD</h2>
      <span class="badge">Phase 1</span>
    </div>

    <div class="message-list" ref="messageListRef">
      <div v-if="state.messages.length === 0" class="empty-state">
        <p class="empty-title">Welcome to ChatCFD</p>
        <p class="empty-hint">Ask questions about your CFD simulation data.</p>
        <p class="empty-hint">Try: "Load the case file" or "Calculate forces on the wall zone"</p>
      </div>
      <MessageBubble
        v-for="msg in state.messages"
        :key="msg.id"
        :role="msg.role"
        :content="msg.content"
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
      <button class="send-btn" @click="sendMessage" :disabled="!inputText.trim()">
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
}

.chat-header h2 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}

.message-list {
  flex: 1;
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
</style>
