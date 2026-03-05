/* REST API client for the playground backend. */

import type { SourceMetadata, SampleData, HealthResponse, LLMConfig, ProviderInfo } from '@/types/api'

const BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail || res.statusText)
  }
  return res.json()
}

export const api = {
  health: () => request<HealthResponse>('/health'),

  // Sources
  listSources: () => request<SourceMetadata[]>('/sources'),
  connectDatabase: (connection_string: string, display_name?: string) =>
    request<{ source_id: string; metadata: SourceMetadata }>('/sources/database', {
      method: 'POST',
      body: JSON.stringify({ connection_string, display_name }),
    }),
  uploadCSV: (file: File, displayName?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (displayName) form.append('display_name', displayName)
    return fetch(`${BASE}/sources/csv`, { method: 'POST', body: form }).then(async r => {
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
      return r.json() as Promise<{ source_id: string; metadata: SourceMetadata }>
    })
  },
  uploadExcel: (file: File, displayName?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (displayName) form.append('display_name', displayName)
    return fetch(`${BASE}/sources/excel`, { method: 'POST', body: form }).then(async r => {
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
      return r.json() as Promise<{ source_id: string; metadata: SourceMetadata }>
    })
  },
  removeSource: (id: string) => request<{ status: string }>(`/sources/${id}`, { method: 'DELETE' }),
  getSource: (id: string) => request<SourceMetadata>(`/sources/${id}`),
  getSample: (sourceId: string, table: string, limit = 10) =>
    request<SampleData>(`/sources/${sourceId}/sample/${encodeURIComponent(table)}?limit=${limit}`),

  // LLM Config
  getLLMConfig: () => request<LLMConfig>('/config/llm'),
  updateLLMConfig: (provider: string, model: string, api_key = '') =>
    request<{ status: string }>('/config/llm', {
      method: 'PUT',
      body: JSON.stringify({ provider, model, api_key }),
    }),
  getProviders: () => request<{ providers: ProviderInfo[] }>('/config/providers'),
}
