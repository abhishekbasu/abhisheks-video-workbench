import { computed, ref } from 'vue'
import { useJobs } from './useJobs'
import type { JobKind } from '../types'

/**
 * Per-view binding over the persistent job store. Each view passes its `kind`;
 * the view shows the currently-selected job for that kind (defaults to the most
 * recent), which survives reloads. `start()` POSTs the operation and registers
 * the returned job id with the store, which handles SSE + persistence.
 */
export function useJob(kind: JobKind) {
  const store = useJobs()
  const active = store.activeFor(kind)
  // True between the click and the job id coming back from the server.
  const pending = ref(false)

  const running = computed(
    () => pending.value || active.value?.status === 'running' || active.value?.status === 'queued',
  )
  const progress = computed(() => (pending.value ? 0 : active.value?.progress ?? 0))
  const stage = computed(() => (pending.value ? 'starting…' : active.value?.stage ?? ''))
  const result = computed(() =>
    !pending.value && active.value?.status === 'done' ? active.value.result : null,
  )
  const error = computed(() => {
    if (pending.value || !active.value) return null
    if (active.value.status === 'error') return active.value.error || 'The job failed.'
    if (active.value.status === 'expired') return active.value.stage
    return null
  })

  /** `starter` performs the POST and resolves to the new job id. */
  async function start(starter: () => Promise<string>, label = '') {
    if (running.value) return
    pending.value = true
    try {
      const id = await starter()
      store.track(kind, label, id)
    } catch (e: any) {
      store.trackError(kind, label, e?.message ?? String(e))
    } finally {
      pending.value = false
    }
  }

  return { running, stage, progress, result, error, start }
}
