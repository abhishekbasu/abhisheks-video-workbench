export interface Capabilities {
  ffmpeg: boolean
  modal: boolean
  api_key: boolean
}

export interface AppConfig {
  models: Record<string, string[]>
  valid_seconds: string[]
  upscale_models: { name: string; desc: string }[]
  default_upscale_model: string
  upscale_scales: number[]
  corners: string[]
  capabilities: Capabilities
}

export interface OutputClip {
  name: string
  url: string
  mtime: number
}

export type JobStatus = 'queued' | 'running' | 'done' | 'error'

export interface JobResult {
  video_url?: string | null
  thumb_url?: string | null
  sprite_url?: string | null
  video_id?: string
  character_id?: string
  name?: string | null
  message?: string
}

export interface JobSnapshot {
  id: string
  status: JobStatus
  progress: number
  stage: string
  result: JobResult | null
  error: string | null
  version: number
}

export type JobKind = 'generate' | 'operate' | 'characters' | 'upscale' | 'brand'

// 'expired' = the server no longer knows this job (e.g. it was restarted) and we
// have no cached result. Persisted to localStorage so jobs survive a reload.
export type EntryStatus = JobStatus | 'expired'

export interface JobEntry {
  id: string
  kind: JobKind
  label: string
  createdAt: number
  status: EntryStatus
  progress: number
  stage: string
  result: JobResult | null
  error: string | null
}
