import { create } from 'zustand'
import type { SourceMetadata, SampleData } from '@/types/api'
import { api } from '@/lib/api'

interface SourceState {
  sources: SourceMetadata[]
  loading: boolean
  error: string | null
  samples: Record<string, SampleData>

  fetchSources: () => Promise<void>
  connectDatabase: (connStr: string, displayName?: string) => Promise<void>
  uploadCSV: (file: File, displayName?: string) => Promise<void>
  uploadExcel: (file: File, displayName?: string) => Promise<void>
  removeSource: (id: string) => Promise<void>
  fetchSample: (sourceId: string, table: string) => Promise<void>
}

export const useSourceStore = create<SourceState>((set, get) => ({
  sources: [],
  loading: false,
  error: null,
  samples: {},

  fetchSources: async () => {
    set({ loading: true, error: null })
    try {
      const sources = await api.listSources()
      set({ sources, loading: false })
    } catch (e) {
      set({ error: (e as Error).message, loading: false })
    }
  },

  connectDatabase: async (connStr, displayName) => {
    set({ loading: true, error: null })
    try {
      const { metadata } = await api.connectDatabase(connStr, displayName)
      set(s => ({ sources: [...s.sources, metadata], loading: false }))
    } catch (e) {
      set({ error: (e as Error).message, loading: false })
      throw e
    }
  },

  uploadCSV: async (file, displayName) => {
    set({ loading: true, error: null })
    try {
      const { metadata } = await api.uploadCSV(file, displayName)
      set(s => ({ sources: [...s.sources, metadata], loading: false }))
    } catch (e) {
      set({ error: (e as Error).message, loading: false })
      throw e
    }
  },

  uploadExcel: async (file, displayName) => {
    set({ loading: true, error: null })
    try {
      const { metadata } = await api.uploadExcel(file, displayName)
      set(s => ({ sources: [...s.sources, metadata], loading: false }))
    } catch (e) {
      set({ error: (e as Error).message, loading: false })
      throw e
    }
  },

  removeSource: async (id) => {
    try {
      await api.removeSource(id)
      set(s => ({ sources: s.sources.filter(src => src.source_id !== id) }))
    } catch (e) {
      set({ error: (e as Error).message })
    }
  },

  fetchSample: async (sourceId, table) => {
    const key = `${sourceId}:${table}`
    try {
      const data = await api.getSample(sourceId, table)
      set(s => ({ samples: { ...s.samples, [key]: data } }))
    } catch (e) {
      set({ error: (e as Error).message })
    }
  },
}))
