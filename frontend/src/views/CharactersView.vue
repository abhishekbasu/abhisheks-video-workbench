<script setup lang="ts">
import { ref } from 'vue'
import { useJob } from '../composables/useJob'
import { postForm } from '../api'
import ResultPanel from '../components/ResultPanel.vue'
import IdleCard from '../components/IdleCard.vue'

const job = useJob('characters')

const name = ref('')
const clipFile = ref<File | null>(null)
const clipPreview = ref<string | null>(null)

function onClip(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  clipFile.value = file
  if (clipPreview.value) URL.revokeObjectURL(clipPreview.value)
  clipPreview.value = URL.createObjectURL(file)
}
function clearClip() {
  clipFile.value = null
  if (clipPreview.value) URL.revokeObjectURL(clipPreview.value)
  clipPreview.value = null
}

function submit() {
  if (!clipFile.value) return
  const form = new FormData()
  form.set('name', name.value)
  form.set('clip', clipFile.value)
  job.start(() => postForm('/api/characters', form), name.value.trim())
}
</script>

<template>
  <div class="grid">
    <div class="panel stagger">
      <div class="section">Source clip</div>
      <div class="field">
        <label class="label">Short clip of the subject <span class="opt">— mp4 / mov / webm</span></label>
        <label class="drop" :class="{ has: clipFile }" v-if="!clipPreview">
          <input type="file" accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm" @change="onClip" />
          <div class="dt">Click to upload a clip</div>
          <div class="dh">A few seconds of the subject is enough to build a character</div>
        </label>
        <div class="preview" v-else>
          <video :src="clipPreview" controls muted playsinline></video>
          <button class="clear" @click="clearClip">remove</button>
        </div>
      </div>

      <div class="section">Identity</div>
      <div class="field">
        <label class="label">Character name</label>
        <input type="text" v-model="name" placeholder="e.g. Alfie" />
        <p class="help">A short label — the API returns a character id you reference later.</p>
      </div>

      <button
        class="btn btn-primary"
        :disabled="job.running.value || !clipFile || !name.trim()"
        @click="submit"
      >
        <span v-if="job.running.value" class="spinner"></span>
        {{ job.running.value ? 'Creating…' : 'Create character' }}
      </button>
    </div>

    <ResultPanel
      :running="job.running.value"
      :progress="job.progress.value"
      :stage="job.stage.value"
      :error="job.error.value"
      :result="job.result.value"
    >
      <IdleCard
        eyebrow="Reusable character"
        title="Build a character once, reuse it everywhere."
        canvas="clip → character id"
      >
        <p class="idle-body">
          Upload a short clip of your subject and give them a name. You'll get a
          <code>character id</code> to drop into the Generate tab's <em>Character ids</em> field.
        </p>
        <p class="idle-note">
          Character support in the create API is newer and may be gated on your account — if it
          errors, the message will say so.
        </p>
      </IdleCard>
    </ResultPanel>
  </div>
</template>
