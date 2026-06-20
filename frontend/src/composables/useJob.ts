import { ref } from 'vue'
import { subscribeJob } from '../api'
import type { JobResult, JobSnapshot } from '../types'

/**
 * Drives one long-running operation: kick it off, follow its SSE progress, and
 * expose reactive state for a view to bind to a ProgressBar + result panel.
 */
export function useJob() {
  const running = ref(false)
  const stage = ref('')
  const progress = ref(0)
  const result = ref<JobResult | null>(null)
  const error = ref<string | null>(null)

  let close: (() => void) | null = null

  function reset() {
    result.value = null
    error.value = null
    stage.value = ''
    progress.value = 0
  }

  /** `starter` performs the POST and resolves to the new job id. */
  async function start(starter: () => Promise<string>) {
    if (running.value) return
    reset()
    running.value = true
    stage.value = 'starting…'
    try {
      const jobId = await starter()
      close = subscribeJob(
        jobId,
        (snap: JobSnapshot) => {
          progress.value = snap.progress
          if (snap.stage) stage.value = snap.stage
          if (snap.status === 'done') {
            result.value = snap.result
            stage.value = snap.result?.message || 'done'
            progress.value = 100
            running.value = false
            close?.()
          } else if (snap.status === 'error') {
            error.value = snap.error || 'The job failed.'
            running.value = false
            close?.()
          }
        },
        (message: string) => {
          if (running.value) {
            error.value = message
            running.value = false
          }
        },
      )
    } catch (e: any) {
      error.value = e?.message ?? String(e)
      running.value = false
    }
  }

  return { running, stage, progress, result, error, start, reset }
}
