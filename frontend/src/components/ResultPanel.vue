<script setup lang="ts">
import type { JobResult } from '../types'
import ProgressBar from './ProgressBar.vue'
import CopyChip from './CopyChip.vue'

defineProps<{
  running: boolean
  progress: number
  stage: string
  error: string | null
  result: JobResult | null
}>()
</script>

<template>
  <div class="panel result-col">
    <ProgressBar v-if="running" :running="running" :progress="progress" :stage="stage" />

    <div v-if="error" class="banner err">
      <span class="bt">Failed.</span> {{ error }}
    </div>

    <!-- character result -->
    <div v-else-if="result && result.character_id" class="rise">
      <p class="idle-eyebrow">Reusable character</p>
      <h3 class="idle-title">{{ result.name || 'Character created' }}</h3>
      <p class="idle-body">
        Drop this id into the <strong>Generate</strong> tab's <em>Character ids</em> field.
      </p>
      <CopyChip label="character id" :value="result.character_id" />
    </div>

    <!-- video result -->
    <div v-else-if="result" class="rise">
      <video v-if="result.video_url" :src="result.video_url" controls autoplay loop muted playsinline></video>
      <p v-if="result.message" class="statusline">✦ {{ result.message }}</p>

      <CopyChip v-if="result.video_id" label="video id" :value="result.video_id" />

      <div class="thumbs" v-if="result.thumb_url || result.sprite_url">
        <div v-if="result.thumb_url">
          <p class="thumb-cap">Thumbnail</p>
          <img :src="result.thumb_url" alt="thumbnail" />
        </div>
        <div v-if="result.sprite_url">
          <p class="thumb-cap">Spritesheet</p>
          <img :src="result.sprite_url" alt="spritesheet" />
        </div>
      </div>

      <p class="statusline" v-if="result.video_url">
        <a :href="result.video_url" download>↓ Download clip</a>
      </p>
    </div>

    <!-- idle -->
    <slot v-else />
  </div>
</template>
