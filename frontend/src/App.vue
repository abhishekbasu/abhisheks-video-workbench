<script setup lang="ts">
import { ref, computed } from 'vue'
import { useConfig } from './composables/useConfig'
import { useTheme } from './composables/useTheme'
import { useJobs } from './composables/useJobs'
import CapabilityBar from './components/CapabilityBar.vue'
import TabNav from './components/TabNav.vue'
import JobHistory from './components/JobHistory.vue'
import GenerateView from './views/GenerateView.vue'
import OperateView from './views/OperateView.vue'
import CharactersView from './views/CharactersView.vue'
import UpscaleView from './views/UpscaleView.vue'
import BrandView from './views/BrandView.vue'
import type { JobKind } from './types'

const { loadError } = useConfig()
const store = useJobs()
const { theme, toggle: toggleTheme } = useTheme()

const tabs = [
  { id: 'generate', label: 'Generate' },
  { id: 'operate', label: 'Extend · Remix · Edit' },
  { id: 'characters', label: 'Characters' },
  { id: 'upscale', label: 'Upscale' },
  { id: 'brand', label: 'Branding' },
]

const views: Record<string, any> = {
  generate: GenerateView,
  operate: OperateView,
  characters: CharactersView,
  upscale: UpscaleView,
  brand: BrandView,
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
        <div class="masthead-tools">
          <button
            class="icon-btn"
            :aria-label="theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'"
            :title="theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'"
            @click="toggleTheme"
          >
            <svg v-if="theme === 'dark'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </svg>
            <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
            </svg>
          </button>
          <button class="jobs-btn" @click="drawerOpen = true">
          <span class="jobs-dot" :class="{ live: store.activeCount.value > 0 }"></span>
          Jobs
          <span v-if="store.activeCount.value > 0" class="jobs-count">{{ store.activeCount.value }}</span>
          </button>
        </div>
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
