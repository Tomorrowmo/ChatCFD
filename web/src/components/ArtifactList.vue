<script setup>
import { computed } from 'vue'
import { useChatStore } from '../stores/chat.js'

const { activeConversation, activeArtifacts, setActiveArtifact } = useChatStore()

const activeIndex = computed(() => activeConversation.value?.activeArtifactIndex ?? -1)

function typeIcon(type) {
  if (type === 'numerical') return '#'
  if (type === 'geometry') return '\u{1F4D0}'
  if (type === 'file') return '\u{1F4C4}'
  return '\u{1F4CB}'
}
</script>

<template>
  <div class="artifact-list" v-if="activeArtifacts.length">
    <div
      v-for="(art, idx) in activeArtifacts"
      :key="art.id"
      class="artifact-item"
      :class="{ active: idx === activeIndex }"
      @click="setActiveArtifact(idx)"
    >
      <span class="item-icon">{{ typeIcon(art.type) }}</span>
      <div class="item-info">
        <div class="item-title truncate">{{ art.title }}</div>
        <div class="item-summary truncate">{{ art.summary }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.artifact-list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.artifact-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 20px;
  cursor: pointer;
  transition: background 0.1s;
}

.artifact-item:hover {
  background: var(--bg-hover);
}

.artifact-item.active {
  background: var(--bg-tertiary);
  border-left: 3px solid var(--accent);
  padding-left: 17px;
}

.item-icon {
  font-size: 16px;
  flex-shrink: 0;
  width: 24px;
  text-align: center;
}

.item-info {
  min-width: 0;
  flex: 1;
}

.item-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.item-summary {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 1px;
}
</style>
