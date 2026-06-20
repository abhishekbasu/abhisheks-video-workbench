<script setup lang="ts">
import { ref, computed } from 'vue'
import { useConfig } from '../composables/useConfig'
import { useJob } from '../composables/useJob'
import { postJson } from '../api'
import ResultPanel from '../components/ResultPanel.vue'
import IdleCard from '../components/IdleCard.vue'

const { config } = useConfig()
const job = useJob('operate')

const op = ref<'extend' | 'remix' | 'edit'>('extend')
const sourceId = ref('')
const prompt = ref('')
const seconds = ref('8')

const allSeconds = computed(() => config.value?.valid_seconds ?? ['4', '8', '12'])
const ops = [
  { id: 'extend', label: 'extend' },
  { id: 'remix', label: 'remix' },
  { id: 'edit', label: 'edit' },
] as const

const hint = computed(
  () =>
    ({
      extend: '+seconds continuation guided by the prompt',
      remix: 'a variation of the clip from a new prompt',
      edit: 'a prompt-based edit of the clip',
    })[op.value],
)

function submit() {
  job.start(
    () =>
      postJson('/api/operate', {
        op: op.value,
        source_id: sourceId.value,
        prompt: prompt.value,
        seconds: seconds.value,
      }),
    `${op.value} · ${sourceId.value.trim()}`,
  )
}
</script>

<template>
  <div class="grid">
    <div class="panel stagger">
      <div class="section">Operation</div>
      <div class="field">
        <div class="seg wide">
          <button v-for="o in ops" :key="o.id" :class="{ on: op === o.id }" @click="op = o.id">
            {{ o.label }}
          </button>
        </div>
        <p class="help">{{ hint }}</p>
      </div>

      <div class="section">Source</div>
      <div class="field mono-input">
        <label class="label">Source video id</label>
        <input type="text" v-model="sourceId" placeholder="video_…" />
        <p class="help">From the Generate tab's <code>video id</code>.</p>
      </div>

      <div class="field">
        <label class="label">Prompt</label>
        <textarea
          v-model="prompt"
          placeholder="What should change, continue, or be reinterpreted?"
        ></textarea>
      </div>

      <div class="field" v-if="op === 'extend'">
        <label class="label">Seconds <span class="opt">— extend only</span></label>
        <div class="seg wide">
          <button v-for="s in allSeconds" :key="s" :class="{ on: seconds === s }" @click="seconds = s">
            {{ s }}s
          </button>
        </div>
      </div>

      <button
        class="btn btn-primary"
        :disabled="job.running.value || !sourceId.trim() || !prompt.trim()"
        @click="submit"
      >
        <span v-if="job.running.value" class="spinner"></span>
        {{ job.running.value ? 'Running…' : 'Run ' + op }}
      </button>
    </div>

    <ResultPanel
      :running="job.running.value"
      :progress="job.progress.value"
      :stage="job.stage.value"
      :error="job.error.value"
      :result="job.result.value"
    >
      <IdleCard eyebrow="Result" title="Operate on an existing clip." canvas="id → new clip">
        <p class="idle-body">
          Paste a <code>video id</code>, choose <em>extend</em>, <em>remix</em> or <em>edit</em>,
          and describe the change. The new clip lands here with its own id — chain operations as
          far as you like.
        </p>
      </IdleCard>
    </ResultPanel>
  </div>
</template>
