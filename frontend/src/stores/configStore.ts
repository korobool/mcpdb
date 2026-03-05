import { create } from 'zustand'
import type { LLMConfig, ProviderInfo } from '@/types/api'
import { api } from '@/lib/api'

interface ConfigState {
  theme: 'light' | 'dark'
  llmConfig: LLMConfig | null
  providers: ProviderInfo[]

  toggleTheme: () => void
  setTheme: (theme: 'light' | 'dark') => void
  fetchLLMConfig: () => Promise<void>
  fetchProviders: () => Promise<void>
  updateLLM: (provider: string, model: string, apiKey?: string) => Promise<void>
}

export const useConfigStore = create<ConfigState>((set) => ({
  theme: (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light',
  llmConfig: null,
  providers: [],

  toggleTheme: () => set(s => {
    const next = s.theme === 'dark' ? 'light' : 'dark'
    document.documentElement.classList.toggle('dark', next === 'dark')
    return { theme: next }
  }),

  setTheme: (theme) => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    set({ theme })
  },

  fetchLLMConfig: async () => {
    try {
      const cfg = await api.getLLMConfig()
      set({ llmConfig: cfg })
    } catch { /* ignore */ }
  },

  fetchProviders: async () => {
    try {
      const { providers } = await api.getProviders()
      set({ providers })
    } catch { /* ignore */ }
  },

  updateLLM: async (provider, model, apiKey) => {
    await api.updateLLMConfig(provider, model, apiKey)
    set({ llmConfig: { provider, model, has_key: !!apiKey } })
  },
}))
