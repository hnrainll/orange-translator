<template>
  <div class="panel">
    <!-- Step 1: 上传和配置 -->
    <section v-if="phase === 'config'" class="card">
      <h2>上传 EPUB</h2>

      <!-- 文件拖放区 -->
      <div
        class="dropzone"
        :class="{ 'drag-over': isDragging }"
        @dragover.prevent="isDragging = true"
        @dragleave="isDragging = false"
        @drop.prevent="onDrop"
        @click="fileInput?.click()"
      >
        <input ref="fileInput" type="file" accept=".epub" class="hidden" @change="onFileSelect" />
        <div v-if="!file">
          <div class="upload-icon">📚</div>
          <p>点击或拖拽 EPUB 文件到此处</p>
        </div>
        <div v-else class="file-info">
          <span class="file-icon">📖</span>
          <span>{{ file.name }}</span>
          <span class="file-size">{{ formatSize(file.size) }}</span>
        </div>
      </div>

      <!-- 翻译配置 -->
      <div class="config-grid">
        <div class="field">
          <label>源语言</label>
          <select v-model="srcLang">
            <option v-for="[code, name] in LANGUAGES" :key="code" :value="code">
              {{ name }} ({{ code }})
            </option>
          </select>
        </div>
        <div class="field">
          <label>目标语言</label>
          <select v-model="tgtLang">
            <option v-for="[code, name] in LANGUAGES" :key="code" :value="code">
              {{ name }} ({{ code }})
            </option>
          </select>
        </div>
        <div class="field">
          <label>翻译模式</label>
          <select v-model="mode">
            <option value="speed">Speed（快速）</option>
            <option value="quality">Quality（高质量）</option>
          </select>
        </div>
        <div class="field">
          <label>翻译引擎</label>
          <select v-model="engine">
            <option value="ollama">Ollama（本地）</option>
            <option value="openai">OpenAI 兼容</option>
          </select>
        </div>
        <div class="field" v-if="engine === 'ollama'">
          <label>Ollama 模型</label>
          <select v-model="model">
            <option value="">自动（按模式选择）</option>
            <option v-for="m in ollamaModels" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
        <div class="field" v-if="engine === 'ollama'">
          <label>Ollama 地址</label>
          <input v-model="ollamaUrl" placeholder="http://localhost:11434" />
        </div>
        <div class="field" v-if="engine === 'openai'">
          <label>API Key</label>
          <input v-model="apiKey" type="password" placeholder="sk-..." />
        </div>
        <div class="field" v-if="engine === 'openai'">
          <label>Base URL</label>
          <input v-model="apiBase" placeholder="https://api.openai.com/v1" />
        </div>
        <div class="field" v-if="engine === 'openai'">
          <label>模型</label>
          <input v-model="model" placeholder="gpt-4o-mini" />
        </div>
      </div>

      <button class="btn-primary" :disabled="!file" @click="startTranslation">
        开始翻译
      </button>
    </section>

    <!-- Step 2: 翻译进度 -->
    <section v-if="phase === 'translating'" class="card">
      <h2>翻译中…</h2>
      <div class="progress-info">
        <p class="chapter-title">{{ currentChapterTitle }}</p>
        <div class="progress-bar-wrap">
          <div class="progress-label">章节</div>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: chapterPct + '%' }"></div>
          </div>
          <span class="progress-pct">{{ chapterDone }}/{{ chapterTotal }}</span>
        </div>
        <div class="progress-bar-wrap" v-if="blockTotal > 0">
          <div class="progress-label">段落</div>
          <div class="progress-bar">
            <div class="progress-fill secondary" :style="{ width: blockPct + '%' }"></div>
          </div>
          <span class="progress-pct">{{ blockIndex }}/{{ blockTotal }}</span>
        </div>
      </div>
      <div class="event-log">
        <div v-for="(ev, i) in recentEvents" :key="i" class="event-item" :class="ev.status">
          <span class="ev-status">{{ statusLabel(ev.status) }}</span>
          <span class="ev-title">{{ ev.chapter_title }}</span>
        </div>
      </div>
    </section>

    <!-- Step 3: 完成 -->
    <section v-if="phase === 'done'" class="card done-card">
      <div class="done-icon">✅</div>
      <h2>翻译完成</h2>
      <a class="btn-primary" :href="`/api/translate/${taskId}/download`" download>
        下载双语 EPUB
      </a>
      <button class="btn-secondary" @click="reset">翻译另一本</button>
    </section>

    <!-- 错误 -->
    <section v-if="phase === 'error'" class="card error-card">
      <div class="done-icon">❌</div>
      <h2>翻译失败</h2>
      <p class="error-msg">{{ errorMsg }}</p>
      <button class="btn-secondary" @click="reset">重试</button>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

type Phase = 'config' | 'translating' | 'done' | 'error'

const LANGUAGES: [string, string][] = [
  ['zh', 'Chinese Simplified'],
  ['zh-TW', 'Chinese Traditional'],
  ['en', 'English'],
  ['ja', 'Japanese'],
  ['ko', 'Korean'],
  ['fr', 'French'],
  ['de', 'German'],
  ['es', 'Spanish'],
  ['pt', 'Portuguese'],
  ['ru', 'Russian'],
  ['ar', 'Arabic'],
  ['it', 'Italian'],
  ['nl', 'Dutch'],
  ['pl', 'Polish'],
  ['tr', 'Turkish'],
  ['vi', 'Vietnamese'],
  ['th', 'Thai'],
]

interface ProgressEvent {
  chapter_index: number
  chapter_total: number
  chapter_title: string
  block_index: number
  block_total: number
  status: string
  message: string
}

const phase = ref<Phase>('config')
const file = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)

// 配置
const srcLang = ref('en')
const tgtLang = ref('zh')
const mode = ref('speed')
const engine = ref('ollama')
const model = ref('')
const ollamaUrl = ref('http://localhost:11434')
const apiKey = ref('')
const apiBase = ref('https://api.openai.com/v1')
const ollamaModels = ref<string[]>([])

// 进度
const taskId = ref('')
const events = ref<ProgressEvent[]>([])
const errorMsg = ref('')

const chapterDone = computed(() => {
  const last = events.value.at(-1)
  if (!last) return 0
  return last.status === 'done' || last.status === 'skipped'
    ? last.chapter_index + 1
    : last.chapter_index
})
const chapterTotal = computed(() => events.value.at(-1)?.chapter_total ?? 0)
const chapterPct = computed(() =>
  chapterTotal.value ? (chapterDone.value / chapterTotal.value) * 100 : 0,
)

const blockIndex = computed(() => events.value.at(-1)?.block_index ?? 0)
const blockTotal = computed(() => events.value.at(-1)?.block_total ?? 0)
const blockPct = computed(() =>
  blockTotal.value ? (blockIndex.value / blockTotal.value) * 100 : 0,
)

const currentChapterTitle = computed(() => {
  const last = events.value.at(-1)
  return last ? last.chapter_title : ''
})

const recentEvents = computed(() =>
  [...events.value].reverse().slice(0, 6),
)

onMounted(fetchOllamaModels)

async function fetchOllamaModels() {
  try {
    const resp = await fetch(`/api/models?ollama_url=${encodeURIComponent(ollamaUrl.value)}`)
    const data = await resp.json()
    ollamaModels.value = data.models ?? []
  } catch {
    ollamaModels.value = []
  }
}

function onDrop(e: DragEvent) {
  isDragging.value = false
  const f = e.dataTransfer?.files[0]
  if (f?.name.endsWith('.epub')) file.value = f
}

function onFileSelect(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (f) file.value = f
}

async function startTranslation() {
  if (!file.value) return
  phase.value = 'translating'
  events.value = []

  const formData = new FormData()
  formData.append('file', file.value)
  formData.append('src', srcLang.value)
  formData.append('tgt', tgtLang.value)
  formData.append('mode', mode.value)
  formData.append('engine', engine.value)
  formData.append('model', model.value)
  formData.append('ollama_url', ollamaUrl.value)
  formData.append('api_key', apiKey.value)
  formData.append('api_base', apiBase.value)

  const resp = await fetch('/api/translate', { method: 'POST', body: formData })
  const data = await resp.json()
  taskId.value = data.task_id

  // 订阅 SSE 进度
  const es = new EventSource(`/api/translate/${taskId.value}/progress`)
  es.onmessage = (e) => {
    const ev: ProgressEvent = JSON.parse(e.data)
    events.value.push(ev)
  }
  es.onerror = async () => {
    es.close()
    // 检查最终状态
    const statusResp = await fetch(`/api/translate/${taskId.value}/status`)
    const statusData = await statusResp.json()
    if (statusData.status === 'done') {
      phase.value = 'done'
    } else {
      errorMsg.value = statusData.error ?? '未知错误'
      phase.value = 'error'
    }
  }
}

function reset() {
  phase.value = 'config'
  file.value = null
  events.value = []
  taskId.value = ''
  errorMsg.value = ''
}

function formatSize(bytes: number): string {
  return bytes > 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${(bytes / 1024).toFixed(0)} KB`
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    done: '✓',
    skipped: '↷',
    translating: '…',
    error: '✗',
  }
  return map[s] ?? s
}
</script>

<style scoped>
.panel { display: flex; flex-direction: column; gap: 1.5rem; }

.card {
  background: #fff;
  border-radius: 12px;
  padding: 2rem;
  box-shadow: 0 1px 3px rgba(0,0,0,.08), 0 4px 16px rgba(0,0,0,.04);
}

h2 { font-size: 1.2rem; font-weight: 600; margin-bottom: 1.5rem; }

/* 拖放区 */
.dropzone {
  border: 2px dashed #cbd5e1;
  border-radius: 10px;
  padding: 2.5rem;
  text-align: center;
  cursor: pointer;
  transition: border-color .2s, background .2s;
  margin-bottom: 1.5rem;
}
.dropzone:hover, .dropzone.drag-over {
  border-color: #ea580c;
  background: #fff7ed;
}
.hidden { display: none; }
.upload-icon { font-size: 2.5rem; margin-bottom: .5rem; }
.file-info { display: flex; align-items: center; gap: .8rem; justify-content: center; }
.file-icon { font-size: 1.5rem; }
.file-size { color: #64748b; font-size: .85rem; }

/* 配置网格 */
.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.field { display: flex; flex-direction: column; gap: .35rem; }
.field label { font-size: .8rem; font-weight: 500; color: #475569; }
.field input, .field select {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: .5rem .7rem;
  font-size: .9rem;
  outline: none;
  transition: border-color .2s;
}
.field input:focus, .field select:focus { border-color: #ea580c; }

/* 按钮 */
.btn-primary {
  display: inline-block;
  width: 100%;
  padding: .75rem;
  background: #ea580c;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  text-align: center;
  text-decoration: none;
  transition: background .2s;
}
.btn-primary:hover:not(:disabled) { background: #c2410c; }
.btn-primary:disabled { opacity: .45; cursor: not-allowed; }

.btn-secondary {
  display: inline-block;
  width: 100%;
  margin-top: .75rem;
  padding: .7rem;
  background: #f1f5f9;
  color: #475569;
  border: none;
  border-radius: 8px;
  font-size: .95rem;
  cursor: pointer;
  transition: background .2s;
}
.btn-secondary:hover { background: #e2e8f0; }

/* 进度 */
.progress-info { display: flex; flex-direction: column; gap: .9rem; margin-bottom: 1.2rem; }
.chapter-title { font-size: .85rem; color: #64748b; min-height: 1.2em; }

.progress-bar-wrap { display: flex; align-items: center; gap: .7rem; }
.progress-label { font-size: .8rem; color: #94a3b8; width: 2.5rem; }
.progress-bar {
  flex: 1;
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: #ea580c;
  border-radius: 4px;
  transition: width .3s ease;
}
.progress-fill.secondary { background: #3b82f6; }
.progress-pct { font-size: .8rem; color: #64748b; width: 4rem; text-align: right; }

/* 事件日志 */
.event-log { display: flex; flex-direction: column; gap: .3rem; }
.event-item {
  display: flex;
  align-items: center;
  gap: .5rem;
  font-size: .82rem;
  color: #64748b;
  padding: .25rem .4rem;
  border-radius: 4px;
}
.event-item.done { color: #16a34a; }
.event-item.error { color: #dc2626; }
.ev-status { width: 1.2rem; text-align: center; }
.ev-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 完成/错误 */
.done-card, .error-card { text-align: center; }
.done-icon { font-size: 3rem; margin-bottom: 1rem; }
.error-msg { color: #dc2626; margin: 1rem 0; font-size: .9rem; }
</style>
