<script setup lang="ts">
defineProps<{ eyebrow: string; title: string; canvas?: string }>()
</script>

<template>
  <div>
    <div class="idle-canvas" v-if="canvas !== ''">{{ canvas || 'awaiting render' }}</div>
    <p class="idle-eyebrow">{{ eyebrow }}</p>
    <h3 class="idle-title">{{ title }}</h3>
    <slot />
  </div>
</template>
