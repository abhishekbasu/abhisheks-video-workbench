<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useConfig } from '../composables/useConfig'
import { useJob } from '../composables/useJob'
import { postForm } from '../api'
import ResultPanel from '../components/ResultPanel.vue'
import IdleCard from '../components/IdleCard.vue'

const { config } = useConfig()
const job = useJob('generate')

const prompt = ref('')
const model = ref('sora-2')
const size = ref('720x1280')
const seconds = ref('8')
const characters = ref('')
const mute = ref(false)
const clean = ref(false)

const imageFile = ref<File | null>(null)
const imagePreview = ref<string | null>(null)

const models = computed(() => Object.keys(config.value?.models ?? { 'sora-2': [] }))
const sizes = computed(() => config.value?.models?.[model.value] ?? [])
const allSeconds = computed(() => config.value?.valid_seconds ?? ['4', '8', '12'])
const ffmpeg = computed(() => config.value?.capabilities?.ffmpeg ?? false)

// Each model gates its sizes — snap to the first allowed when the model changes.
watch(model, () => {
  if (sizes.value.length && !sizes.value.includes(size.value)) size.value = sizes.value[0]
})
watch(sizes, (s) => {
  if (s.length && !s.includes(size.value)) size.value = s[0]
})

function onImage(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  imageFile.value = file
  if (imagePreview.value) URL.revokeObjectURL(imagePreview.value)
  imagePreview.value = URL.createObjectURL(file)
}
function clearImage() {
  imageFile.value = null
  if (imagePreview.value) URL.revokeObjectURL(imagePreview.value)
  imagePreview.value = null
}

function submit() {
  const form = new FormData()
  form.set('prompt', prompt.value)
  form.set('model', model.value)
  form.set('size', size.value)
  form.set('seconds', seconds.value)
  form.set('characters', characters.value)
  form.set('mute', String(mute.value && ffmpeg.value))
  form.set('clean', String(clean.value))
  if (imageFile.value) form.set('image', imageFile.value)
  job.start(() => postForm('/api/generate', form), prompt.value.trim())
}
</script>

<template>
  <div class="grid">
    <!-- controls -->
    <div class="panel stagger">
      <div class="section">Source</div>

      <div class="field">
        <label class="label">Seed image <span class="opt">— optional, leave empty for text-to-video</span></label>
        <label class="drop" :class="{ has: imageFile }" v-if="!imagePreview">
          <input type="file" accept="image/*" @change="onImage" />
          <div class="dt">Click to upload a seed image</div>
          <div class="dh">It's cover-cropped to the exact video size before generation</div>
        </label>
        <div class="preview" v-else>
          <img :src="imagePreview" alt="seed preview" />
          <button class="clear" @click="clearImage">remove</button>
        </div>
      </div>

      <div class="field">
        <label class="label">Prompt</label>
        <textarea
          v-model="prompt"
          placeholder="Describe the motion or scene. One clear action; subtle motion reads best."
        ></textarea>
        <p class="help">Plain English. Avoid moderation triggers — see README.</p>
      </div>

      <div class="section">Generation</div>
      <div class="field">
        <label class="label">Model</label>
        <div class="seg wide">
          <button
            v-for="m in models"
            :key="m"
            :class="{ on: model === m }"
            @click="model = m"
          >
            {{ m }}
          </button>
        </div>
      </div>

      <div class="row">
        <div class="field">
          <label class="label">Seconds</label>
          <div class="seg wide">
            <button v-for="s in allSeconds" :key="s" :class="{ on: seconds === s }" @click="seconds = s">
              {{ s }}s
            </button>
          </div>
        </div>
        <div class="field">
          <label class="label">Size</label>
          <select v-model="size">
            <option v-for="s in sizes" :key="s" :value="s">{{ s }}</option>
          </select>
        </div>
      </div>

      <div class="section">Advanced</div>
      <div class="field mono-input">
        <label class="label">Character ids <span class="opt">— optional</span></label>
        <input type="text" v-model="characters" placeholder="char_abc, char_def" />
        <p class="help">Comma-separated. Build characters in the Characters tab.</p>
      </div>

      <div class="row">
        <label class="check" :class="{ checked: mute && ffmpeg, disabled: !ffmpeg }">
          <input type="checkbox" v-model="mute" :disabled="!ffmpeg" />
          <span class="box"><svg width="11" height="11" viewBox="0 0 12 12"><path d="M2.5 6.5l2.5 2.5 4.5-5.5" stroke="#1c0d06" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
          <span>
            <span class="ctitle">Mute output</span>
            <span class="cdesc">{{ ffmpeg ? 'Strip the audio track' : 'Needs ffmpeg on PATH' }}</span>
          </span>
        </label>
        <label class="check" :class="{ checked: clean }">
          <input type="checkbox" v-model="clean" />
          <span class="box"><svg width="11" height="11" viewBox="0 0 12 12"><path d="M2.5 6.5l2.5 2.5 4.5-5.5" stroke="#1c0d06" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
          <span>
            <span class="ctitle">Force fresh</span>
            <span class="cdesc">Ignore the resume cache</span>
          </span>
        </label>
      </div>

      <button class="btn btn-primary" :disabled="job.running.value || !prompt.trim()" @click="submit">
        <span v-if="job.running.value" class="spinner"></span>
        {{ job.running.value ? 'Generating…' : 'Generate' }}
      </button>
    </div>

    <!-- result -->
    <ResultPanel
      :running="job.running.value"
      :progress="job.progress.value"
      :stage="job.stage.value"
      :error="job.error.value"
      :result="job.result.value"
    >
      <IdleCard eyebrow="Result" title="Your clip will appear here." canvas="prompt → video">
        <p class="idle-body">
          Write a prompt — optionally seed it with an image — and press <strong>Generate</strong>.
          The finished clip, its thumbnail, spritesheet and a <code>video id</code> for follow-up
          operations land in this column.
        </p>
        <p class="idle-note">
          Typical wait: 2–4 minutes for <code>sora-2</code>, longer for <code>sora-2-pro</code>.
          Re-runs of the same request resume the in-flight job instead of paying again.
        </p>
      </IdleCard>
    </ResultPanel>
  </div>
</template>
