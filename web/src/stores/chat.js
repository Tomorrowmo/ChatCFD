import { reactive, computed } from 'vue'

const STORAGE_KEY = 'chatcfd.state.v1'

function genId() {
  return 'conv_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36)
}

function newConversation(title = '新对话') {
  const now = new Date().toISOString()
  return {
    id: genId(),
    title,
    messages: [],
    artifacts: [],
    activeArtifactIndex: -1,
    created_at: now,
    updated_at: now,
  }
}

const state = reactive({
  conversations: {}, // id -> conversation
  activeConversationId: null,
  artifactPanelOpen: false, // global: is the right panel showing an artifact?
})

// --- Persistence ---
let saveTimer = null
function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    try {
      const snapshot = {
        conversations: state.conversations,
        activeConversationId: state.activeConversationId,
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot))
    } catch (e) {
      console.warn('[chatStore] Failed to persist state:', e)
    }
  }, 250)
}

function loadFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return false
    const data = JSON.parse(raw)
    if (!data || typeof data !== 'object') return false
    state.conversations = data.conversations || {}
    state.activeConversationId = data.activeConversationId || null
    // Validate active id
    if (!state.activeConversationId || !state.conversations[state.activeConversationId]) {
      const ids = Object.keys(state.conversations)
      state.activeConversationId = ids.length ? ids[0] : null
    }
    return Object.keys(state.conversations).length > 0
  } catch (e) {
    console.warn('[chatStore] Failed to load state:', e)
    return false
  }
}

// Initialize on module load
if (!loadFromStorage()) {
  const conv = newConversation('新对话')
  state.conversations[conv.id] = conv
  state.activeConversationId = conv.id
  scheduleSave()
}

let nextMsgId = 1
let nextArtifactId = 1
// Seed from existing data to avoid id collisions
for (const conv of Object.values(state.conversations)) {
  for (const m of conv.messages || []) {
    if (typeof m.id === 'number' && m.id >= nextMsgId) nextMsgId = m.id + 1
  }
  for (const a of conv.artifacts || []) {
    if (typeof a.id === 'number' && a.id >= nextArtifactId) nextArtifactId = a.id + 1
  }
}

export function useChatStore() {
  // --- Conversation management ---
  function getActiveConversation() {
    let conv = state.conversations[state.activeConversationId]
    if (!conv) {
      const created = createConversation('新对话')
      conv = state.conversations[created]
    }
    return conv
  }

  function createConversation(title = '新对话') {
    const conv = newConversation(title)
    state.conversations[conv.id] = conv
    state.activeConversationId = conv.id
    scheduleSave()
    return conv.id
  }

  function deleteConversation(id) {
    if (!state.conversations[id]) return
    delete state.conversations[id]
    if (state.activeConversationId === id) {
      const ids = Object.keys(state.conversations)
      if (ids.length) {
        state.activeConversationId = ids[0]
      } else {
        const created = newConversation('新对话')
        state.conversations[created.id] = created
        state.activeConversationId = created.id
      }
    }
    scheduleSave()
  }

  function setActiveConversation(id) {
    if (state.conversations[id]) {
      state.activeConversationId = id
      scheduleSave()
    }
  }

  function renameConversation(id, title) {
    const conv = state.conversations[id]
    if (conv) {
      conv.title = title
      conv.updated_at = new Date().toISOString()
      scheduleSave()
    }
  }

  // --- Reactive views on active conversation ---
  const activeMessages = computed(() => getActiveConversation()?.messages || [])
  const activeArtifacts = computed(() => getActiveConversation()?.artifacts || [])
  const activeConversation = computed(() => getActiveConversation())
  const conversationList = computed(() => {
    return Object.values(state.conversations).sort(
      (a, b) => new Date(b.updated_at) - new Date(a.updated_at)
    )
  })

  const activeArtifact = computed(() => {
    const conv = getActiveConversation()
    if (!conv) return null
    if (conv.activeArtifactIndex >= 0 && conv.activeArtifactIndex < conv.artifacts.length) {
      return conv.artifacts[conv.activeArtifactIndex]
    }
    return null
  })

  function touchActive() {
    const conv = getActiveConversation()
    if (conv) conv.updated_at = new Date().toISOString()
  }

  // --- Messages ---
  function addMessage(role, content, artifacts = []) {
    const conv = getActiveConversation()
    const msg = {
      id: nextMsgId++,
      role,
      content,
      artifacts,
      created_at: new Date().toISOString(),
    }
    conv.messages.push(msg)
    // Auto-title from first user message
    if (role === 'user' && (conv.title === '新对话' || conv.title === '未命名对话')) {
      conv.title = content.slice(0, 30) || '新对话'
    }
    touchActive()
    scheduleSave()
    return msg
  }

  function getOrCreateStreamingMessage() {
    const conv = getActiveConversation()
    const last = conv.messages[conv.messages.length - 1]
    if (last && last.role === 'assistant' && last._streaming) {
      return last
    }
    const msg = {
      id: nextMsgId++,
      role: 'assistant',
      content: '',
      parts: [],
      artifacts: [],
      created_at: new Date().toISOString(),
      _streaming: true,
    }
    conv.messages.push(msg)
    return msg
  }

  function appendToStreaming(text) {
    const msg = getOrCreateStreamingMessage()
    msg.content += text
    const lastPart = msg.parts[msg.parts.length - 1]
    if (lastPart && lastPart.type === 'text') {
      lastPart.content += text
    } else {
      msg.parts.push({ type: 'text', content: text })
    }
    touchActive()
  }

  function addToolCallPart(tool, args) {
    const msg = getOrCreateStreamingMessage()
    const part = {
      type: 'tool',
      tool,
      args,
      status: 'running',
      summary: '',
      started_at: Date.now(),
      finished_at: null,
    }
    msg.parts.push(part)
    touchActive()
    return part
  }

  function finishToolCallPart(tool, summary) {
    const msg = getOrCreateStreamingMessage()
    for (let i = msg.parts.length - 1; i >= 0; i--) {
      const p = msg.parts[i]
      if (p.type === 'tool' && p.tool === tool && p.status === 'running') {
        p.status = 'done'
        p.summary = summary
        p.finished_at = Date.now()
        break
      }
    }
    touchActive()
  }

  function finalizeStreaming(content, artifactRefs) {
    const msg = getOrCreateStreamingMessage()
    if (content) msg.content = content
    msg.artifacts = artifactRefs || []
    for (const p of msg.parts) {
      if (p.type === 'tool' && p.status === 'running') {
        p.status = 'done'
        p.finished_at = Date.now()
      }
    }
    delete msg._streaming
    touchActive()
    scheduleSave()
  }

  function addArtifact(artifact) {
    const conv = getActiveConversation()
    let filePath = artifact.file_path || null
    if (!filePath && artifact.output_files && artifact.output_files.length > 0) {
      filePath = artifact.output_files[0]
    }
    const a = {
      id: nextArtifactId++,
      title: artifact.title || 'Untitled',
      type: artifact.type || 'numerical',
      summary: artifact.summary || '',
      data: artifact.data || null,
      output_files: artifact.output_files || [],
      file_path: filePath,
      created_at: new Date().toISOString(),
    }
    conv.artifacts.push(a)
    conv.activeArtifactIndex = conv.artifacts.length - 1
    state.artifactPanelOpen = true  // auto-open when new artifact arrives
    touchActive()
    scheduleSave()
    return a
  }

  function setActiveArtifact(index) {
    const conv = getActiveConversation()
    if (index >= 0 && index < conv.artifacts.length) {
      conv.activeArtifactIndex = index
      state.artifactPanelOpen = true
      scheduleSave()
    }
  }

  function openArtifactPanel() {
    state.artifactPanelOpen = true
  }

  function closeArtifactPanel() {
    state.artifactPanelOpen = false
  }

  function clearAll() {
    const conv = getActiveConversation()
    conv.messages.length = 0
    conv.artifacts.length = 0
    conv.activeArtifactIndex = -1
    scheduleSave()
  }

  return {
    state,
    // conversation management
    createConversation,
    deleteConversation,
    setActiveConversation,
    renameConversation,
    getActiveConversation,
    // reactive views
    activeConversation,
    activeMessages,
    activeArtifacts,
    activeArtifact,
    conversationList,
    // messages / artifacts
    addMessage,
    getOrCreateStreamingMessage,
    appendToStreaming,
    addToolCallPart,
    finishToolCallPart,
    finalizeStreaming,
    addArtifact,
    setActiveArtifact,
    openArtifactPanel,
    closeArtifactPanel,
    clearAll,
  }
}
