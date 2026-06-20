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
