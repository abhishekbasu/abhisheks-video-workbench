<script setup lang="ts">
import { useJobs } from '../composables/useJobs'
import type { JobEntry, JobKind } from '../types'

defineProps<{ open: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'open-job', payload: { kind: JobKind; id: string }): void
}>()

const store = useJobs()

const KIND_BADGE: Record<JobKind, string> = {
  generate: 'GEN',
  operate: 'EDIT',
  characters: 'CHAR',
  upscale: 'UP',
}

function relTime(ms: number): string {
  const s = Math.floor((Date.now() - ms) / 1000)
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function thumb(job: JobEntry): string | null {
  return job.result?.thumb_url ?? null
}

function onRow(job: JobEntry) {
  emit('open-job', { kind: job.kind, id: job.id })
}
</script>

<template>
  <div>
    <transition name="fade">
      <div v-if="open" class="drawer-backdrop" @click="emit('close')"></div>
    </transition>
    <transition name="slide">
      <aside v-if="open" class="drawer" role="dialog" aria-label="Job history">
        <div class="drawer-head">
          <span class="drawer-title">Jobs</span>
          <div class="drawer-actions">
            <button v-if="store.jobs.value.length" class="copy" @click="store.clear()">clear all</button>
            <button class="copy" @click="emit('close')">close</button>
          </div>
        </div>

        <div v-if="!store.recent.value.length" class="drawer-empty">
          No jobs yet. Anything you run shows up here — and survives a refresh.
        </div>

        <ul class="job-list" v-else>
          <li
            v-for="job in store.recent.value"
            :key="job.id"
            class="job-row"
            :class="job.status"
            @click="onRow(job)"
          >
            <div class="job-thumb">
              <img v-if="thumb(job)" :src="thumb(job)!" alt="" />
              <span v-else class="job-badge">{{ KIND_BADGE[job.kind] || '—' }}</span>
            </div>
            <div class="job-body">
              <div class="job-label">{{ job.label }}</div>
              <div class="job-meta">
                <span class="job-kind">{{ job.kind }}</span>
                <span class="job-sep">·</span>
                <span>{{ relTime(job.createdAt) }}</span>
              </div>
              <div
                v-if="job.status === 'running' || job.status === 'queued'"
                class="job-track"
              >
                <div
                  class="job-fill"
                  :class="{ indeterminate: job.progress === 0 }"
                  :style="{ width: job.progress + '%' }"
                ></div>
              </div>
            </div>
            <div class="job-status">
              <span v-if="job.status === 'running' || job.status === 'queued'" class="js running"
                >{{ job.progress }}%</span
              >
              <span v-else-if="job.status === 'done'" class="js done">done</span>
              <span v-else-if="job.status === 'error'" class="js error">failed</span>
              <span v-else class="js expired">expired</span>
              <button class="job-x" title="Remove" @click.stop="store.remove(job.id)">×</button>
            </div>
          </li>
        </ul>
      </aside>
    </transition>
  </div>
</template>
