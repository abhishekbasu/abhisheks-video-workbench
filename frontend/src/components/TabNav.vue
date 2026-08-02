<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ tabs: { id: string; label: string }[]; active: string }>()
const emit = defineEmits<{ (e: 'select', id: string): void }>()
const buttons = ref<HTMLButtonElement[]>([])

function selectFromKeyboard(event: KeyboardEvent, index: number) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const next =
    event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? props.tabs.length - 1
        : (index + (event.key === 'ArrowRight' ? 1 : -1) + props.tabs.length) % props.tabs.length
  emit('select', props.tabs[next].id)
  buttons.value[next]?.focus()
}
</script>

<template>
  <nav class="tabs" role="tablist" aria-label="Production tools">
    <button
      v-for="(tab, i) in tabs"
      :key="tab.id"
      :ref="(element) => { if (element) buttons[i] = element as HTMLButtonElement }"
      class="tab"
      :class="{ active: tab.id === active }"
      type="button"
      role="tab"
      :aria-selected="tab.id === active"
      :tabindex="tab.id === active ? 0 : -1"
      @click="$emit('select', tab.id)"
      @keydown="selectFromKeyboard($event, i)"
    >
      <span class="idx">{{ String(i + 1).padStart(2, '0') }}</span>{{ tab.label }}
    </button>
  </nav>
</template>
