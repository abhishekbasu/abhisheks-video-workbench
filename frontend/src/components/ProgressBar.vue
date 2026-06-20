<script setup lang="ts">
defineProps<{
  running: boolean
  progress: number
  stage: string
}>()
</script>

<template>
  <div class="progress">
    <div class="progress-head">
      <span class="progress-stage">{{ stage || 'working…' }}</span>
      <span class="progress-pct">{{ progress }}%</span>
    </div>
    <div class="track">
      <div
        class="fill"
        :class="{ indeterminate: running && progress === 0 }"
        :style="{ width: progress + '%' }"
      ></div>
    </div>
  </div>
</template>
