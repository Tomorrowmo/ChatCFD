<script setup>
import { ref, onMounted } from 'vue'

const emit = defineEmits(['close'])

const SETTINGS_KEY = 'chatcfd.settings.v1'
const AGENT_URL = 'http://localhost:8080'

const MODELS = [
  'openai/qwen3-max',
  'openai/qwen-plus',
  'openai/qwen-max',
  'openai/qwen-turbo',
]

const model = ref('openai/qwen3-max')
const apiBase = ref('')
const saving = ref(false)
const statusMsg = ref('')

onMounted(() => {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    if (raw) {
      const s = JSON.parse(raw)
      model.value = s.model || model.value
      apiBase.value = s.api_base || ''
    }
  } catch (e) {
    console.warn('[Settings] load failed:', e)
  }
})

async function onSave() {
  saving.value = true
  statusMsg.value = ''
  try {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ model: model.value, api_base: apiBase.value })
    )
    const resp = await fetch(`${AGENT_URL}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: model.value, api_base: apiBase.value }),
    })
    if (resp.ok) {
      statusMsg.value = '已保存'
      setTimeout(() => emit('close'), 600)
    } else {
      statusMsg.value = `保存失败 (${resp.status})`
    }
  } catch (e) {
    statusMsg.value = `保存失败: ${e.message}`
  } finally {
    saving.value = false
  }
}

function onCancel() {
  emit('close')
}

function onBackdropClick(e) {
  if (e.target === e.currentTarget) emit('close')
}
</script>

<template>
  <div class="modal-backdrop" @click="onBackdropClick">
    <div class="modal">
      <div class="modal-header">
        <h3>设置</h3>
        <button class="close-btn" @click="onCancel">×</button>
      </div>
      <div class="modal-body">
        <div class="form-row">
          <label>模型</label>
          <select v-model="model">
            <option v-for="m in MODELS" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
        <div class="form-row">
          <label>LLM API Base URL</label>
          <input type="text" v-model="apiBase" placeholder="留空使用默认" />
        </div>
        <div v-if="statusMsg" class="status">{{ statusMsg }}</div>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" @click="onCancel">取消</button>
        <button class="btn-primary" @click="onSave" :disabled="saving">
          {{ saving ? '保存中...' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 12px;
  width: 420px;
  max-width: 90vw;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}

.modal-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: 22px;
  cursor: pointer;
  line-height: 1;
  padding: 0 4px;
}

.close-btn:hover {
  color: var(--text-primary);
}

.modal-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-row label {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}

.form-row select,
.form-row input {
  background: var(--bg-input, var(--bg-secondary));
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  color: var(--text-primary);
  font-size: 13px;
}

.form-row select:focus,
.form-row input:focus {
  outline: none;
  border-color: var(--accent);
}

.status {
  font-size: 12px;
  color: var(--text-secondary);
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--border);
}

.btn-primary,
.btn-secondary {
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  border: none;
  cursor: pointer;
}

.btn-primary {
  background: var(--accent);
  color: #fff;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}
</style>
