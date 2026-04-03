<script setup>
import { useChatStore } from '../stores/chat.js'

const props = defineProps({
  role: { type: String, required: true },
  content: { type: String, required: true },
  artifacts: { type: Array, default: () => [] },
})

const { state, setActiveArtifact } = useChatStore()

function onArtifactClick(artifactRef) {
  const idx = state.artifacts.findIndex((a) => a.id === artifactRef.id)
  if (idx >= 0) {
    setActiveArtifact(idx)
  }
}
</script>

<template>
  <div class="bubble-row" :class="role">
    <div class="bubble" :class="role">
      <div class="bubble-content">{{ content }}</div>
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

.bubble-content {
  white-space: pre-wrap;
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
