<script setup lang="ts">
import { ref, computed } from 'vue'
import { useConfig } from './composables/useConfig'
import { useJobs } from './composables/useJobs'
import CapabilityBar from './components/CapabilityBar.vue'
import TabNav from './components/TabNav.vue'
import JobHistory from './components/JobHistory.vue'
import GenerateView from './views/GenerateView.vue'
import OperateView from './views/OperateView.vue'
import CharactersView from './views/CharactersView.vue'
import UpscaleView from './views/UpscaleView.vue'
import type { JobKind } from './types'

const { loadError } = useConfig()
const store = useJobs()

const tabs = [
  { id: 'generate', label: 'Generate' },
  { id: 'operate', label: 'Extend · Remix · Edit' },
  { id: 'characters', label: 'Characters' },
  { id: 'upscale', label: 'Upscale' },
]

const views: Record<string, any> = {
  generate: GenerateView,
  operate: OperateView,
  characters: CharactersView,
  upscale: UpscaleView,
}

const active = ref('generate')
const activeView = computed(() => views[active.value])

const drawerOpen = ref(false)

function openJob({ kind, id }: { kind: JobKind; id: string }) {
  if (!views[kind]) return // ignore entries from a removed feature
  store.select(kind, id)
  active.value = kind
  drawerOpen.value = false
}
</script>

<template>
  <div class="shell">
    <header class="masthead">
      <div class="brand">
        <span class="kicker"><span class="dot"></span>OpenAI Videos API · Sora</span>
        <h1 class="wordmark">Sora&nbsp;Studio <em>/ prompt → video</em></h1>
        <p class="lede">
          A focused control surface for generating, extending, remixing and editing short Sora
          clips — with reusable characters and GPU upscaling. Generation is paid and async; a clip
          usually takes a few minutes (longer for <code>sora-2-pro</code>).
        </p>
      </div>
      <div class="masthead-right">
        <button class="jobs-btn" @click="drawerOpen = true">
          <span class="jobs-dot" :class="{ live: store.activeCount.value > 0 }"></span>
          Jobs
          <span v-if="store.activeCount.value > 0" class="jobs-count">{{ store.activeCount.value }}</span>
        </button>
        <CapabilityBar />
      </div>
    </header>

    <div v-if="loadError" class="banner err" style="margin-top: 28px">
      <span class="bt">Couldn't reach the backend.</span> {{ loadError }} — is the API running on
      <code>:8000</code>?
    </div>

    <TabNav :tabs="tabs" :active="active" @select="(id) => (active = id)" />

    <keep-alive>
      <component :is="activeView" :key="active" />
    </keep-alive>

    <footer class="footer">
      <span>Sora Studio · local frontend for the OpenAI Videos API</span>
      <span>Vue 3 · FastAPI · Real-ESRGAN on Modal</span>
    </footer>

    <JobHistory :open="drawerOpen" @close="drawerOpen = false" @open-job="openJob" />
  </div>
</template>
