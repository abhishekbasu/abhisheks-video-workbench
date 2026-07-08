import { ref } from 'vue'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'sora-studio-theme'

function initialTheme(): Theme {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'light' || saved === 'dark') return saved
  // fall back to the OS preference, defaulting to the studio's native dark
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

const theme = ref<Theme>(initialTheme())

function apply(t: Theme) {
  document.documentElement.setAttribute('data-theme', t)
}

// apply immediately on module load so there's no flash of the wrong theme
apply(theme.value)

export function useTheme() {
  function setTheme(t: Theme) {
    theme.value = t
    localStorage.setItem(STORAGE_KEY, t)
    apply(t)
  }

  function toggle() {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  return { theme, setTheme, toggle }
}
