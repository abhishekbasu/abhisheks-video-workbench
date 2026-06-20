<script setup lang="ts">
defineProps<{ tabs: { id: string; label: string }[]; active: string }>()
defineEmits<{ (e: 'select', id: string): void }>()
</script>

<template>
  <nav class="tabs">
    <button
      v-for="(tab, i) in tabs"
      :key="tab.id"
      class="tab"
      :class="{ active: tab.id === active }"
      @click="$emit('select', tab.id)"
    >
      <span class="idx">{{ String(i + 1).padStart(2, '0') }}</span>{{ tab.label }}
    </button>
  </nav>
</template>
