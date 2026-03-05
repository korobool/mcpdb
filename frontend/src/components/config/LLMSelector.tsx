import { useState } from 'react'
import { useConfigStore } from '@/stores/configStore'
import { Settings2, Check, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

export function LLMSelector() {
  const { llmConfig, providers, updateLLM } = useConfigStore()
  const [expanded, setExpanded] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState(llmConfig?.provider || '')
  const [selectedModel, setSelectedModel] = useState(llmConfig?.model || '')
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const currentProvider = providers.find(p => p.name === selectedProvider)

  const handleSave = async () => {
    if (!selectedProvider || !selectedModel) return
    setSaving(true)
    setError('')
    try {
      await updateLLM(selectedProvider, selectedModel, apiKey || undefined)
      setExpanded(false)
      setApiKey('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border-b border-sidebar-border">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full px-3 py-2 hover:bg-muted"
      >
        <Settings2 className="w-3.5 h-3.5 text-muted-foreground" />
        <span className="text-xs font-medium uppercase text-muted-foreground">LLM Provider</span>
        {llmConfig && (
          <span className="ml-auto text-xs text-muted-foreground">
            {llmConfig.provider}
          </span>
        )}
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          <select
            value={selectedProvider}
            onChange={e => {
              setSelectedProvider(e.target.value)
              const p = providers.find(p => p.name === e.target.value)
              if (p) setSelectedModel(p.models[0])
            }}
            className="w-full px-2 py-1.5 text-sm rounded border border-input bg-background"
          >
            <option value="">Select provider...</option>
            {providers.map(p => (
              <option key={p.name} value={p.name}>{p.display_name}</option>
            ))}
          </select>

          {currentProvider && (
            <select
              value={selectedModel}
              onChange={e => setSelectedModel(e.target.value)}
              className="w-full px-2 py-1.5 text-sm rounded border border-input bg-background"
            >
              {currentProvider.models.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          )}

          {currentProvider?.env_key && (
            <input
              type="password"
              placeholder={`API Key (or set ${currentProvider.env_key})`}
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              className="w-full px-2 py-1.5 text-sm rounded border border-input bg-background"
            />
          )}

          {error && <p className="text-xs text-destructive">{error}</p>}

          <button
            onClick={handleSave}
            disabled={saving || !selectedProvider || !selectedModel}
            className={cn(
              "w-full flex items-center justify-center gap-1 px-2 py-1.5 text-sm rounded",
              "bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
            )}
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            Apply
          </button>
        </div>
      )}
    </div>
  )
}
