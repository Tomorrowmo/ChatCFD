import { reactive, computed } from 'vue'

const state = reactive({
  messages: [],
  artifacts: [],
  activeArtifactIndex: -1,
})

let nextMsgId = 1
let nextArtifactId = 1

export function useChatStore() {
  const activeArtifact = computed(() => {
    if (state.activeArtifactIndex >= 0 && state.activeArtifactIndex < state.artifacts.length) {
      return state.artifacts[state.activeArtifactIndex]
    }
    return null
  })

  function addMessage(role, content, artifacts = []) {
    const msg = {
      id: nextMsgId++,
      role,
      content,
      artifacts,
      created_at: new Date().toISOString(),
    }
    state.messages.push(msg)
    return msg
  }

  function addArtifact(artifact) {
    const a = {
      id: nextArtifactId++,
      title: artifact.title || 'Untitled',
      type: artifact.type || 'numerical',
      summary: artifact.summary || '',
      data: artifact.data || null,
      output_files: artifact.output_files || [],
      file_path: artifact.file_path || null,
      created_at: new Date().toISOString(),
    }
    state.artifacts.push(a)
    // Auto-select the new artifact
    state.activeArtifactIndex = state.artifacts.length - 1
    return a
  }

  function setActiveArtifact(index) {
    if (index >= 0 && index < state.artifacts.length) {
      state.activeArtifactIndex = index
    }
  }

  function clearAll() {
    state.messages.length = 0
    state.artifacts.length = 0
    state.activeArtifactIndex = -1
  }

  return {
    state,
    activeArtifact,
    addMessage,
    addArtifact,
    setActiveArtifact,
    clearAll,
  }
}
