<script setup lang="ts">
import { ref, computed } from 'vue'
import { useConfig } from '../composables/useConfig'
import { useJob } from '../composables/useJob'
import { postJson } from '../api'
import ResultPanel from '../components/ResultPanel.vue'
import IdleCard from '../components/IdleCard.vue'

const { config } = useConfig()
const job = useJob()

const sourceId = ref('')
const prompt = ref('')
const targetSeconds = ref(60)
const autoUpscale = ref(false)

const modal = computed(() => config.value?.capabilities?.modal ?? false)
const ffmpeg = computed(() => config.value?.capabilities?.ffmpeg ?? false)
const mmss = computed(() => {
  const m = Math.floor(targetSeconds.value / 60)
  const s = targetSeconds.value % 60
  return `${targetSeconds.value}s · ${m}:${String(s).padStart(2, '0')}`
})

function submit() {
  job.start(() =>
    postJson('/api/long-form', {
      source_id: sourceId.value,
      prompt: prompt.value,
      target_seconds: targetSeconds.value,
      auto_upscale: autoUpscale.value && modal.value,
    }),
  )
}
</script>

<template>
  <div class="grid">
    <div class="panel stagger">
      <div class="section">Source</div>
      <div class="field mono-input">
        <label class="label">Source video id</label>
        <input type="text" v-model="sourceId" placeholder="video_…" />
        <p class="help">Start from a generated 8s or 12s clip.</p>
      </div>

      <div class="field">
        <label class="label">Story prompt</label>
        <textarea
          v-model="prompt"
          placeholder="Describe the unfolding scene. What happens over the next few minutes?"
        ></textarea>
      </div>

      <div class="section">Duration</div>
      <div class="field">
        <div class="range">
          <input type="range" min="24" max="300" step="12" v-model.number="targetSeconds" />
          <span class="val">{{ mmss }}</span>
        </div>
        <p class="help">Chains 12-second extensions and stitches them — up to 5 minutes.</p>
      </div>

      <div class="field">
        <label class="check" :class="{ checked: autoUpscale && modal, disabled: !modal }">
          <input type="checkbox" v-model="autoUpscale" :disabled="!modal" />
          <span class="box"><svg width="11" height="11" viewBox="0 0 12 12"><path d="M2.5 6.5l2.5 2.5 4.5-5.5" stroke="#0c0f06" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
          <span>
            <span class="ctitle">Auto-upscale (2×)</span>
            <span class="cdesc">{{ modal ? 'Run Real-ESRGAN on the stitched result' : 'Needs Modal setup' }}</span>
          </span>
        </label>
      </div>

      <div class="banner warn" v-if="!ffmpeg">
        <span class="bt">ffmpeg required.</span> Long Form stitches segments with ffmpeg — install it
        first (<code>brew install ffmpeg</code>).
      </div>

      <button
        class="btn btn-primary"
        :disabled="job.running.value || !sourceId.trim() || !prompt.trim() || !ffmpeg"
        @click="submit"
      >
        <span v-if="job.running.value" class="spinner"></span>
        {{ job.running.value ? 'Rendering…' : 'Generate Long Form' }}
      </button>
    </div>

    <ResultPanel
      :running="job.running.value"
      :progress="job.progress.value"
      :stage="job.stage.value"
      :error="job.error.value"
      :result="job.result.value"
    >
      <IdleCard eyebrow="Result" title="Create a cinematic long take." canvas="chain → 5 min">
        <p class="idle-body">
          Provide the <code>video id</code> of a starting clip, describe what happens next, and
          choose a target duration. The app chains 12-second extensions and stitches them together
          seamlessly.
        </p>
        <p class="idle-note">
          <strong>Heads up:</strong> a 5-minute video takes ~25 API calls and may run for a long
          time. Progress is checkpointed — re-run with the same prompt and duration to resume.
        </p>
      </IdleCard>
    </ResultPanel>
  </div>
</template>
