<script setup lang="ts">
import { computed } from 'vue'
import { useConfig } from '../composables/useConfig'

const { config } = useConfig()

const caps = computed(() => {
  const c = config.value?.capabilities
  return [
    { key: 'api_key', label: 'OPENAI KEY', on: !!c?.api_key },
    { key: 'ffmpeg', label: 'FFMPEG', on: !!c?.ffmpeg },
    { key: 'modal', label: 'MODAL GPU', on: !!c?.modal },
  ]
})
</script>

<template>
  <div class="caps" v-if="config">
    <span
      v-for="cap in caps"
      :key="cap.key"
      class="cap"
      :class="cap.on ? 'on' : 'off'"
      :title="cap.on ? cap.label + ' available' : cap.label + ' not configured'"
    >
      <span class="led"></span>{{ cap.label }}
    </span>
  </div>
</template>
