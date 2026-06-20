<script setup lang="ts">
import { ref, computed } from 'vue'
import { useConfig } from './composables/useConfig'
import CapabilityBar from './components/CapabilityBar.vue'
import TabNav from './components/TabNav.vue'
import GenerateView from './views/GenerateView.vue'
import OperateView from './views/OperateView.vue'
import LongFormView from './views/LongFormView.vue'
import CharactersView from './views/CharactersView.vue'
import UpscaleView from './views/UpscaleView.vue'

const { loadError } = useConfig()

const tabs = [
  { id: 'generate', label: 'Generate' },
  { id: 'operate', label: 'Extend · Remix · Edit' },
  { id: 'long', label: 'Long Form' },
  { id: 'characters', label: 'Characters' },
  { id: 'upscale', label: 'Upscale' },
]

const views: Record<string, any> = {
  generate: GenerateView,
  operate: OperateView,
  long: LongFormView,
  characters: CharactersView,
  upscale: UpscaleView,
}

const active = ref('generate')
const activeView = computed(() => views[active.value])
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
      <CapabilityBar />
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
  </div>
</template>
