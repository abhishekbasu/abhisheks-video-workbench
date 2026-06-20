<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ label: string; value: string }>()
const copied = ref(false)

async function copy() {
  try {
    await navigator.clipboard.writeText(props.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 1400)
  } catch {
    /* clipboard blocked — no-op */
  }
}
</script>

<template>
  <div class="idchip">
    <span class="k">{{ label }}</span>
    <span class="v" :title="value">{{ value }}</span>
    <button class="copy" :class="{ done: copied }" @click="copy">
      {{ copied ? 'copied' : 'copy' }}
    </button>
  </div>
</template>
