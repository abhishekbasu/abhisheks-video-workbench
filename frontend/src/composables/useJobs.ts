import { ref, computed } from 'vue'
import { getJob, subscribeJob } from '../api'
import type { JobEntry, JobKind, JobSnapshot } from '../types'

/**
 * Process-wide job store, persisted to localStorage so jobs survive a tab
 * close/refresh. On load it rehydrates the saved entries and, for any that were
 * still running, re-opens the SSE stream (or refreshes a snapshot) so progress
 * and results come back. Completed results are cached locally too, so a finished
 * clip is still viewable even if the backend was restarted (the mp4 lives in
 * output/ and is served from /files regardless).
 */

const STORAGE_KEY = 'sora.jobs.v1'
const MAX = 40

const jobs = ref<JobEntry[]>(load())
// kind -> id of the entry that view is currently showing (ephemeral; defaults
// to the most recent entry of that kind on reload).
const selected = ref<Record<string, string>>({})
// live SSE closers, keyed by job id (never persisted)
const closers = new Map<string, () => void>()
let started = false

function load(): JobEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs.value.slice(0, MAX)))
  } catch {
    /* storage full / disabled — degrade to in-memory only */
  }
}

function find(id: string): JobEntry | undefined {
  return jobs.value.find((j) => j.id === id)
}

function applySnap(entry: JobEntry, snap: JobSnapshot) {
  entry.status = snap.status
  // The upstream Sora % can wobble (and even drop to 0 mid-render), which made
  // the bar jump backwards. Clamp it monotonic within a job: only ever move
  // forward while running, and snap to 100 once done. A fresh run is always a
  // new entry starting at 0, so this never traps an old value.
  if (typeof snap.progress === 'number') {
    if (snap.status === 'done') entry.progress = 100
    else if (snap.status === 'running' || snap.status === 'queued')
      entry.progress = Math.max(entry.progress, snap.progress)
    else entry.progress = snap.progress
  }
  if (snap.stage) entry.stage = snap.stage
  if (snap.result) entry.result = snap.result
  if (snap.error) entry.error = snap.error
  persist()
}

function connect(entry: JobEntry) {
  if (closers.has(entry.id)) return
  const close = subscribeJob(
    entry.id,
    (snap) => {
      applySnap(entry, snap)
      if (snap.status === 'done' || snap.status === 'error') {
        closers.get(entry.id)?.()
        closers.delete(entry.id)
      }
    },
    () => {
      closers.delete(entry.id)
    },
  )
  closers.set(entry.id, close)
}

async function rehydrate() {
  // Snapshot the list now; entries are mutated in place.
  for (const entry of [...jobs.value]) {
    if (entry.status === 'done' || entry.status === 'error' || entry.status === 'expired') {
      continue // terminal — keep the cached result/error as-is
    }
    // Was running/queued when we last saw it — ask the server where it stands.
    try {
      const snap = await getJob(entry.id)
      if (snap === null) {
        // Backend no longer knows this job (likely restarted).
        if (entry.result) {
          entry.status = 'done'
        } else {
          entry.status = 'expired'
          entry.stage = 'expired — backend restarted before it finished'
        }
        persist()
      } else {
        applySnap(entry, snap)
        if (snap.status === 'running' || snap.status === 'queued') connect(entry)
      }
    } catch {
      /* transient network error — leave the entry; user can retry */
    }
  }
}

function track(kind: JobKind, label: string, id: string): JobEntry {
  const entry: JobEntry = {
    id,
    kind,
    label: label || kind,
    createdAt: Date.now(),
    status: 'queued',
    progress: 0,
    stage: 'starting…',
    result: null,
    error: null,
  }
  jobs.value.unshift(entry)
  if (jobs.value.length > MAX) jobs.value.length = MAX
  selected.value = { ...selected.value, [kind]: id }
  persist()
  // Connect the REACTIVE proxy from the array (not the raw `entry`), so the SSE
  // updates that mutate it actually trigger Vue re-renders.
  const tracked = jobs.value.find((j) => j.id === id) ?? entry
  connect(tracked)
  return tracked
}

/** Record a failure that happened before a job id was issued (e.g. a 400). */
function trackError(kind: JobKind, label: string, message: string): JobEntry {
  const entry: JobEntry = {
    id: `local-${Date.now()}`,
    kind,
    label: label || kind,
    createdAt: Date.now(),
    status: 'error',
    progress: 0,
    stage: 'failed',
    result: null,
    error: message,
  }
  jobs.value.unshift(entry)
  selected.value[kind] = entry.id
  persist()
  return entry
}

function activeFor(kind: JobKind) {
  return computed<JobEntry | undefined>(() => {
    const sel = selected.value[kind]
    if (sel) {
      const e = find(sel)
      if (e) return e
    }
    return jobs.value.find((j) => j.kind === kind) // list is newest-first
  })
}

function select(kind: JobKind, id: string) {
  // Replace the object so the change is unambiguously reactive.
  selected.value = { ...selected.value, [kind]: id }
}

function remove(id: string) {
  closers.get(id)?.()
  closers.delete(id)
  jobs.value = jobs.value.filter((j) => j.id !== id)
  for (const k of Object.keys(selected.value)) {
    if (selected.value[k] === id) delete selected.value[k]
  }
  persist()
}

function clear() {
  for (const close of closers.values()) close()
  closers.clear()
  jobs.value = []
  selected.value = {}
  persist()
}

const recent = computed(() => [...jobs.value].sort((a, b) => b.createdAt - a.createdAt))
const activeCount = computed(
  () => jobs.value.filter((j) => j.status === 'running' || j.status === 'queued').length,
)

export function useJobs() {
  if (!started) {
    started = true
    rehydrate()
  }
  return { jobs, recent, activeCount, selected, track, trackError, activeFor, select, remove, clear }
}
