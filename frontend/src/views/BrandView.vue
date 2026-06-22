<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfig } from '../composables/useConfig'
import { useJob } from '../composables/useJob'
import { postForm, getOutputs } from '../api'
import type { OutputClip } from '../types'
import ResultPanel from '../components/ResultPanel.vue'
import IdleCard from '../components/IdleCard.vue'

const { config } = useConfig()
const job = useJob('brand')

const outputs = ref<OutputClip[]>([])
const sourceName = ref('')

const uploadFile = ref<File | null>(null)
const uploadPreview = ref<string | null>(null)

const logoFile = ref<File | null>(null)
const logoPreview = ref<string | null>(null)

const corner = ref('bottom-right')
const opacity = ref(0.9)
const size = ref(0.18)

const ffmpeg = computed(() => config.value?.capabilities?.ffmpeg ?? false)

const CORNERS = [
  { id: 'top-left', label: 'Top left' },
  { id: 'top-right', label: 'Top right' },
  { id: 'bottom-left', label: 'Bottom left' },
  { id: 'bottom-right', label: 'Bottom right' },
]

async function refresh() {
  try {
    outputs.value = await getOutputs()
    if (!sourceName.value && outputs.value.length) sourceName.value = outputs.value[0].name
  } catch {
    /* leave empty */
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

function onLogo(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  logoFile.value = file
  if (logoPreview.value) URL.revokeObjectURL(logoPreview.value)
  logoPreview.value = URL.createObjectURL(file)
}
function clearLogo() {
  logoFile.value = null
  if (logoPreview.value) URL.revokeObjectURL(logoPreview.value)
  logoPreview.value = null
}

const canRun = computed(
  () => ffmpeg.value && !!logoFile.value && (!!uploadFile.value || !!sourceName.value),
)

function submit() {
  if (!logoFile.value) return
  const form = new FormData()
  form.set('logo', logoFile.value)
  form.set('corner', corner.value)
  form.set('opacity', String(opacity.value))
  form.set('size', String(size.value))
  if (uploadFile.value) form.set('upload', uploadFile.value)
  else form.set('source_name', sourceName.value)
  const label = `${corner.value} · ${uploadFile.value?.name || sourceName.value}`
  job.start(() => postForm('/api/brand', form), label)
}
</script>

<template>
  <div class="grid">
    <div class="panel stagger">
      <div class="section">Logo</div>
      <div class="field">
        <label class="label">Branding logo <span class="opt">— PNG with transparency works best</span></label>
        <label class="drop" :class="{ has: logoFile }" v-if="!logoPreview">
          <input type="file" accept="image/png,image/webp,image/jpeg,image/svg+xml" @change="onLogo" />
          <div class="dt">Click to upload a logo</div>
          <div class="dh">Transparent PNG keeps only the mark visible</div>
        </label>
        <div class="preview logo-preview" v-else>
          <img :src="logoPreview" alt="logo preview" />
          <button class="clear" @click="clearLogo">remove</button>
        </div>
      </div>

      <div class="section">Video</div>
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

      <div class="section">Placement</div>
      <div class="field">
        <label class="label">Corner</label>
        <div class="corner-grid">
          <button
            v-for="c in CORNERS"
            :key="c.id"
            class="corner-cell"
            :class="['c-' + c.id, { on: corner === c.id }]"
            :title="c.label"
            @click="corner = c.id"
          >
            <span class="corner-dot"></span>
            <span class="corner-name">{{ c.label }}</span>
          </button>
        </div>
      </div>

      <div class="row">
        <div class="field">
          <label class="label">Opacity</label>
          <div class="range">
            <input type="range" min="0.2" max="1" step="0.05" v-model.number="opacity" />
            <span class="val">{{ Math.round(opacity * 100) }}%</span>
          </div>
        </div>
        <div class="field">
          <label class="label">Size</label>
          <div class="range">
            <input type="range" min="0.06" max="0.4" step="0.01" v-model.number="size" />
            <span class="val">{{ Math.round(size * 100) }}% w</span>
          </div>
        </div>
      </div>

      <div class="banner warn" v-if="!ffmpeg">
        <span class="bt">ffmpeg required.</span> Overlaying a logo re-encodes the clip with ffmpeg —
        install it first (<code>brew install ffmpeg</code>).
      </div>

      <button class="btn btn-primary" :disabled="job.running.value || !canRun" @click="submit">
        <span v-if="job.running.value" class="spinner"></span>
        {{ job.running.value ? 'Applying…' : 'Apply branding' }}
      </button>
    </div>

    <ResultPanel
      :running="job.running.value"
      :progress="job.progress.value"
      :stage="job.stage.value"
      :error="job.error.value"
      :result="job.result.value"
    >
      <IdleCard eyebrow="Branded result" title="Stamp your mark on any clip." canvas="clip + logo → branded">
        <p class="idle-body">
          Upload a logo, pick a clip (or upload one), choose a corner and how strong the watermark
          sits, and press <strong>Apply branding</strong>. The logo is overlaid with its
          transparency preserved and saved next to the original as
          <code>&lt;name&gt;_branded.mp4</code> — audio intact.
        </p>
        <p class="idle-note">
          A transparent PNG gives the cleanest result. Size and opacity are relative to the video,
          so the same settings look consistent across clips.
        </p>
      </IdleCard>
    </ResultPanel>
  </div>
</template>
