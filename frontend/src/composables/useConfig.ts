import { ref } from 'vue'
import { getConfig } from '../api'
import type { AppConfig } from '../types'

// Loaded once and shared across every view (module-level singleton).
const config = ref<AppConfig | null>(null)
const loadError = ref<string | null>(null)
let started = false

export function useConfig() {
  if (!started) {
    started = true
    getConfig()
      .then((c) => (config.value = c))
      .catch((e) => (loadError.value = e?.message ?? String(e)))
  }
  return { config, loadError }
}
