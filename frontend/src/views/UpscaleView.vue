<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useConfig } from '../composables/useConfig'
import { useJob } from '../composables/useJob'
import { postForm, getOutputs } from '../api'
import type { OutputClip } from '../types'
import ResultPanel from '../components/ResultPanel.vue'
import IdleCard from '../components/IdleCard.vue'

const { config } = useConfig()
const job = useJob()

const outputs = ref<OutputClip[]>([])
const sourceName = ref('')
const model = ref('')
const scale = ref(2)

const uploadFile = ref<File | null>(null)
const uploadPreview = ref<string | null>(null)

const upscaleModels = computed(() => config.value?.upscale_models ?? [])
const scales = computed(() => config.value?.upscale_scales ?? [2, 3, 4])
const modal = computed(() => config.value?.capabilities?.modal ?? false)

// Default the model once config arrives.
watch(
  () => config.value?.default_upscale_model,
  (m) => {
    if (m && !model.value) model.value = m
  },
  { immediate: true },
)

async function refresh() {
  try {
    outputs.value = await getOutputs()
    if (!sourceName.value && outputs.value.length) sourceName.value = outputs.value[0].name
  } catch {
    /* leave list empty */
  }
}
onMounted(refresh)

function onUpload(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  uploadFile.value = file
  if (uploadPreview.value) URL.revokeObjectURL(uploadPreview.value)
  uploadPreview.value = URL.createObjectURL(file)
}
function clearUpload() {
  uploadFile.value = null
  if (uploadPreview.value) URL.revokeObjectURL(uploadPreview.value)
  uploadPreview.value = null
}

const canRun = computed(() => modal.value && (!!uploadFile.value || !!sourceName.value))

function submit() {
  const form = new FormData()
  form.set('model', model.value)
  form.set('scale', String(scale.value))
  if (uploadFile.value) form.set('upload', uploadFile.value)
  else form.set('source_name', sourceName.value)
  job.start(() => postForm('/api/upscale', form))
}
</script>

<template>
  <div class="grid">
    <div class="panel stagger">
      <div class="section">Source</div>

      <div class="field">
        <label class="label">Generated clip <span class="opt">— output/*.mp4</span></label>
        <div style="display: flex; gap: 10px">
          <select v-model="sourceName" :disabled="!!uploadFile" style="flex: 1">
            <option v-if="!outputs.length" value="">No clips in output/ yet</option>
            <option v-for="o in outputs" :key="o.name" :value="o.name">{{ o.name }}</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="refresh">Refresh</button>
        </div>
        <p class="help">Newest first. Refresh after generating.</p>
      </div>

      <div class="field">
        <label class="label">…or upload any video</label>
        <label class="drop" :class="{ has: uploadFile }" v-if="!uploadPreview">
          <input type="file" accept="video/*" @change="onUpload" />
          <div class="dt">Click to upload a video</div>
          <div class="dh">Overrides the selection above</div>
        </label>
        <div class="preview" v-else>
          <video :src="uploadPreview" controls muted playsinline></video>
          <button class="clear" @click="clearUpload">remove</button>
        </div>
      </div>

      <div class="section">Enhancement</div>
      <div class="field">
        <label class="label">Model</label>
        <select v-model="model">
          <option v-for="m in upscaleModels" :key="m.name" :value="m.name">
            {{ m.name }} — {{ m.desc }}
          </option>
        </select>
        <p class="help">Runs remotely on a Modal GPU — nothing heavy installs locally.</p>
      </div>

      <div class="field">
        <label class="label">Scale</label>
        <div class="seg wide">
          <button v-for="s in scales" :key="s" :class="{ on: scale === s }" @click="scale = s">
            {{ s }}×
          </button>
        </div>
        <p class="help">720×1280 → 2× = 1440×2560 · 4× = 2880×5120.</p>
      </div>

      <div class="banner warn" v-if="!modal">
        <span class="bt">Modal not configured.</span> Run <code>uv run modal setup</code> once, then
        <code>make deploy-upscaler</code>.
      </div>

      <button class="btn btn-primary" :disabled="job.running.value || !canRun" @click="submit">
        <span v-if="job.running.value" class="spinner"></span>
        {{ job.running.value ? 'Upscaling…' : 'Upscale' }}
      </button>
    </div>

    <ResultPanel
      :running="job.running.value"
      :progress="job.progress.value"
      :stage="job.stage.value"
      :error="job.error.value"
      :result="job.result.value"
    >
      <IdleCard eyebrow="Upscaled result" title="Sharper, bigger — after the fact." canvas="clip → 4K">
        <p class="idle-body">
          Pick any finished clip (or upload one), choose a Real-ESRGAN model and scale, and press
          <strong>Upscale</strong>. The enhanced clip plays here and is saved next to the original
          as <code>&lt;name&gt;_&lt;scale&gt;x.mp4</code> — audio intact.
        </p>
        <p class="idle-note">
          Runs on a Modal GPU — a few cents per clip; 1–2 minutes on the default model, plus a short
          cold start after idle.
        </p>
      </IdleCard>
    </ResultPanel>
  </div>
</template>
