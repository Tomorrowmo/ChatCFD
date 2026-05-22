<script setup>
import { ref, computed } from 'vue'
import { useChatStore } from '../stores/chat.js'
import { useBreakpoint } from '../composables/useBreakpoint.js'
import SettingsModal from './SettingsModal.vue'

const {
  state,
  conversationList,
  createConversation,
  deleteConversation,
  setActiveConversation,
} = useChatStore()

const props = defineProps({
  mobileOpen: { type: Boolean, default: false },
})
const emit = defineEmits(['update:pinned', 'navigate'])

const { isMobile } = useBreakpoint()

const showSettings = ref(false)
const pinned = ref(false)            // user clicked the pin button (desktop)
const hovering = ref(false)          // mouse is over sidebar (desktop)
const expandedDesktop = ref(false)   // hover OR pinned (desktop)
let collapseTimer = null

// On mobile the sidebar is a drawer: its expanded state follows mobileOpen.
// On desktop it follows hover/pin.
const expanded = computed(() =>
  isMobile.value ? props.mobileOpen : expandedDesktop.value
)

function onEnter() {
  if (isMobile.value) return
  if (collapseTimer) {
    clearTimeout(collapseTimer)
    collapseTimer = null
  }
  hovering.value = true
  expandedDesktop.value = true
}

function onLeave() {
  if (isMobile.value) return
  hovering.value = false
  if (pinned.value) return
  // Small delay so small mouse movements don't cause flicker
  collapseTimer = setTimeout(() => {
    if (!hovering.value && !pinned.value) {
      expandedDesktop.value = false
    }
  }, 150)
}

function togglePin() {
  pinned.value = !pinned.value
  emit('update:pinned', pinned.value)
  if (pinned.value) {
    expandedDesktop.value = true
  } else if (!hovering.value) {
    expandedDesktop.value = false
  }
}

function onNewChat() {
  createConversation('新对话')
  emit('navigate')
}

function onSelect(id) {
  setActiveConversation(id)
  emit('navigate')
}

function onDelete(id, ev) {
  ev.stopPropagation()
  if (confirm('删除这个对话？')) {
    deleteConversation(id)
  }
}

function onOpenSettings() {
  showSettings.value = true
  emit('navigate')
}

function relativeTime(iso) {
  const t = new Date(iso).getTime()
  const diff = (Date.now() - t) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前'
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前'
  if (diff < 86400 * 7) return Math.floor(diff / 86400) + ' 天前'
  return new Date(iso).toLocaleDateString()
}
</script>

<template>
  <aside
    class="sidebar"
    :class="{ expanded, pinned, mobile: isMobile, 'mobile-open': isMobile && mobileOpen }"
    @mouseenter="onEnter"
    @mouseleave="onLeave"
  >
    <!-- Top: logo + pin toggle -->
    <div class="sidebar-top">
      <button class="icon-btn logo" title="ChatCFD">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2 L4 7 v10 l8 5 8-5 V7 z" stroke-linejoin="round"/>
          <path d="M12 22 V12 M4 7 l8 5 8-5" stroke-linejoin="round"/>
        </svg>
      </button>
      <span class="brand" v-show="expanded">ChatCFD</span>
      <button
        class="icon-btn pin-btn"
        v-show="expanded && !isMobile"
        @click="togglePin"
        :title="pinned ? '取消固定' : '固定展开'"
      >
        <svg v-if="pinned" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 6 6 18 M6 6 l12 12"/>
        </svg>
        <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 5 H19 M15 5 v6 l3 3 H6 l3-3 V5 M12 14 v7" stroke-linejoin="round"/>
        </svg>
      </button>
      <!-- Mobile: close drawer -->
      <button
        class="icon-btn close-btn"
        v-show="isMobile && mobileOpen"
        @click="emit('navigate')"
        title="关闭"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 6 6 18 M6 6 l12 12" stroke-linecap="round"/>
        </svg>
      </button>
    </div>

    <!-- New chat -->
    <button class="nav-item primary" @click="onNewChat" title="新对话">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 5 v14 M5 12 h14" stroke-linecap="round"/>
        </svg>
      </span>
      <span class="nav-label" v-show="expanded">新对话</span>
    </button>

    <!-- History section -->
    <div class="section" v-show="expanded">
      <div class="section-header">最近对话</div>
      <div class="conv-list">
        <div
          v-for="conv in conversationList"
          :key="conv.id"
          class="conv-item"
          :class="{ active: conv.id === state.activeConversationId }"
          @click="onSelect(conv.id)"
        >
          <div class="conv-title truncate">{{ conv.title }}</div>
          <div class="conv-time">{{ relativeTime(conv.updated_at) }}</div>
          <button class="delete-btn" @click="onDelete(conv.id, $event)" title="删除">×</button>
        </div>
      </div>
    </div>

    <!-- Collapsed-mode history icon (only visible when collapsed) -->
    <button class="nav-item" v-show="!expanded" title="对话历史">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="9"/>
          <path d="M12 7 v5 l3 2" stroke-linecap="round"/>
        </svg>
      </span>
    </button>

    <!-- Spacer -->
    <div class="spacer"></div>

    <!-- Settings -->
    <button class="nav-item" @click="onOpenSettings" title="设置">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15 a1.65 1.65 0 0 0 .33 1.82 l.06.06 a2 2 0 1 1-2.83 2.83 l-.06-.06 a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51 V21 a2 2 0 0 1-4 0 v-.09 A1.65 1.65 0 0 0 9 19.4 a1.65 1.65 0 0 0-1.82.33 l-.06.06 a2 2 0 1 1-2.83-2.83 l.06-.06 a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1 H3 a2 2 0 0 1 0-4 h.09 A1.65 1.65 0 0 0 4.6 9 a1.65 1.65 0 0 0-.33-1.82 l-.06-.06 a2 2 0 1 1 2.83-2.83 l.06.06 a1.65 1.65 0 0 0 1.82.33 H9 a1.65 1.65 0 0 0 1-1.51 V3 a2 2 0 0 1 4 0 v.09 a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33 l.06-.06 a2 2 0 1 1 2.83 2.83 l-.06.06 a1.65 1.65 0 0 0-.33 1.82 V9 a1.65 1.65 0 0 0 1.51 1 H21 a2 2 0 0 1 0 4 h-.09 a1.65 1.65 0 0 0-1.51 1 z"/>
        </svg>
      </span>
      <span class="nav-label" v-show="expanded">设置</span>
    </button>

    <SettingsModal v-if="showSettings" @close="showSettings = false" />
  </aside>
</template>

<style scoped>
.sidebar {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: 56px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  padding: 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow: hidden;
  transition: width 0.18s ease;
  z-index: 50;
}

.sidebar.expanded {
  width: 260px;
  box-shadow: 2px 0 18px rgba(0, 0, 0, 0.25);
}

.sidebar.expanded.pinned {
  box-shadow: none;
}

.sidebar-top {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 4px;
  margin-bottom: 4px;
  min-height: 32px;
}

.brand {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
}

.icon-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  color: var(--text-secondary);
  border: none;
  border-radius: 6px;
  cursor: pointer;
  padding: 0;
  flex-shrink: 0;
  transition: background 0.1s, color 0.1s;
}

.icon-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.logo {
  color: var(--accent);
}

.pin-btn {
  width: 24px;
  height: 24px;
}

.close-btn {
  margin-left: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 36px;
  padding: 0 8px;
  border-radius: 6px;
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
  transition: background 0.1s, color 0.1s;
  overflow: hidden;
  white-space: nowrap;
}

.nav-item:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.nav-item.primary {
  color: var(--text-primary);
}

.nav-item.primary:hover {
  background: var(--accent);
  color: #fff;
}

.nav-icon {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.nav-label {
  flex: 1;
  text-align: left;
}

.section {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.section-header {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 6px 10px;
}

.conv-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-height: 0;
}

.conv-item {
  padding: 8px 28px 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 12px;
  position: relative;
  transition: background 0.1s;
}

.conv-item:hover {
  background: var(--bg-tertiary);
}

.conv-item.active {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.conv-title {
  font-weight: 500;
  line-height: 1.3;
}

.conv-time {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
}

.truncate {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.delete-btn {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  opacity: 0;
  background: transparent;
  color: var(--text-secondary);
  border: none;
  cursor: pointer;
  font-size: 16px;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  line-height: 1;
  transition: opacity 0.1s, background 0.1s;
}

.conv-item:hover .delete-btn {
  opacity: 0.7;
}

.conv-item .delete-btn:hover {
  opacity: 1;
  background: rgba(0, 0, 0, 0.08);
}

.spacer {
  flex: 1;
}

/* ───────────── Mobile (≤768px): off-canvas drawer ───────────── */
@media (max-width: 768px) {
  .sidebar,
  .sidebar.expanded {
    width: 280px;
    max-width: 85vw;
    transform: translateX(-100%);
    transition: transform 0.22s ease;
    box-shadow: none;
  }

  .sidebar.mobile-open {
    transform: translateX(0);
    box-shadow: 2px 0 24px rgba(0, 0, 0, 0.35);
  }

  /* Bigger touch targets */
  .nav-item {
    height: 44px;
  }

  .conv-item {
    padding-top: 11px;
    padding-bottom: 11px;
  }

  .delete-btn {
    opacity: 0.6;
  }
}
</style>
