import type { AppConfig, JobSnapshot, OutputClip } from './types'

async function errorText(res: Response): Promise<string> {
  try {
    const data = await res.json()
    if (typeof data?.detail === 'string') return data.detail
    return JSON.stringify(data)
  } catch {
    return `${res.status} ${res.statusText}`
  }
}

export async function getConfig(): Promise<AppConfig> {
  const res = await fetch('/api/config')
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

export async function getOutputs(): Promise<OutputClip[]> {
  const res = await fetch('/api/outputs')
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

/** Fetch a job's current snapshot. Returns null if the server doesn't know it
 *  (404 — e.g. the backend was restarted since the job ran). */
export async function getJob(id: string): Promise<JobSnapshot | null> {
  const res = await fetch(`/api/jobs/${id}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

async function startJob(path: string, init: RequestInit): Promise<string> {
  // `path` is already a full API path (e.g. "/api/generate"), matching
  // getConfig/getOutputs — do not prepend "/api" again.
  const res = await fetch(path, { method: 'POST', ...init })
  if (!res.ok) throw new Error(await errorText(res))
  const { job_id } = await res.json()
  return job_id
}

export function postJson(path: string, body: unknown): Promise<string> {
  return startJob(path, {
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function postForm(path: string, form: FormData): Promise<string> {
  return startJob(path, { body: form })
}

/**
 * Subscribe to a job's live progress over SSE. Calls `onSnap` for every update;
 * returns a function that closes the stream (call it on a terminal status to
 * stop EventSource from auto-reconnecting to a finished job).
 */
export function subscribeJob(
  jobId: string,
  onSnap: (snap: JobSnapshot) => void,
  onError: (message: string) => void,
): () => void {
  const es = new EventSource(`/api/jobs/${jobId}/events`)
  let closed = false
  const close = () => {
    if (!closed) {
      closed = true
      es.close()
    }
  }
  es.onmessage = (e) => {
    try {
      onSnap(JSON.parse(e.data) as JobSnapshot)
    } catch {
      /* ignore malformed frames */
    }
  }
  es.onerror = () => {
    // Only surface an error if the stream dies before reaching a terminal state.
    if (!closed) onError('Lost connection to the job stream.')
  }
  return close
}
