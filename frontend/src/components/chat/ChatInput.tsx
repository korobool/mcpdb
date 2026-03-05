import { useState, useRef, useEffect } from 'react'
import { Send, Square, Zap, Brain, BarChart3, Layers, Search } from 'lucide-react'
import { useChatStore } from '@/stores/chatStore'
import { useSourceStore } from '@/stores/sourceStore'
import type { QueryMode } from '@/types/api'
import { cn } from '@/lib/utils'

const MODES: { value: QueryMode | undefined; label: string; icon: typeof Zap; desc: string }[] = [
  { value: undefined, label: 'Auto', icon: Zap, desc: 'Auto-detect mode' },
  { value: 'quick', label: 'Quick', icon: Zap, desc: 'Context-only answer' },
  { value: 'simple', label: 'Simple', icon: Search, desc: 'Single query' },
  { value: 'optimization_required', label: 'Optimize', icon: BarChart3, desc: 'Cost-aware sampling' },
  { value: 'extended', label: 'Extended', icon: Layers, desc: 'Multi-step analysis' },
  { value: 'deep', label: 'Deep', icon: Brain, desc: 'Investigation-based' },
]

export function ChatInput() {
  const [input, setInput] = useState('')
  const [modeOverride, setModeOverride] = useState<QueryMode | undefined>()
  const [showModes, setShowModes] = useState(false)
  const { sendQuery, isQuerying, cancelQuery } = useChatStore()
  const sources = useSourceStore(s => s.sources)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const disabled = sources.length === 0

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSubmit = () => {
    if (!input.trim() || isQuerying || disabled) return
    sendQuery(input.trim(), modeOverride)
    setInput('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const selectedMode = MODES.find(m => m.value === modeOverride) || MODES[0]
  const ModeIcon = selectedMode.icon

  return (
    <div className="border-t border-border p-3">
      <div className="flex items-end gap-2">
        <div className="relative">
          <button
            onClick={() => setShowModes(!showModes)}
            className={cn(
              "flex items-center gap-1 px-2 py-1.5 text-xs rounded border border-input hover:bg-muted",
              modeOverride && "border-primary text-primary"
            )}
            title={selectedMode.desc}
          >
            <ModeIcon className="w-3.5 h-3.5" />
            {selectedMode.label}
          </button>
          {showModes && (
            <div className="absolute bottom-full left-0 mb-1 bg-popover border border-border rounded-md shadow-lg py-1 z-10 min-w-[160px]">
              {MODES.map(mode => {
                const Icon = mode.icon
                return (
                  <button
                    key={mode.label}
                    onClick={() => { setModeOverride(mode.value); setShowModes(false) }}
                    className={cn(
                      "flex items-center gap-2 w-full px-3 py-1.5 text-sm hover:bg-muted",
                      mode.value === modeOverride && "bg-muted font-medium"
                    )}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    <span>{mode.label}</span>
                    <span className="text-xs text-muted-foreground ml-auto">{mode.desc}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        <div className="flex-1 relative">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={disabled ? "Connect a data source first..." : "Ask a question about your data..."}
            disabled={disabled}
            rows={1}
            className={cn(
              "w-full px-3 py-2 text-sm rounded-lg border border-input bg-background resize-none",
              "focus:outline-none focus:ring-2 focus:ring-ring",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
            style={{ minHeight: '38px', maxHeight: '120px' }}
            onInput={e => {
              const el = e.currentTarget
              el.style.height = 'auto'
              el.style.height = Math.min(el.scrollHeight, 120) + 'px'
            }}
          />
        </div>

        {isQuerying ? (
          <button
            onClick={cancelQuery}
            className="p-2 rounded-lg bg-destructive text-destructive-foreground hover:opacity-90"
            title="Cancel"
          >
            <Square className="w-4 h-4" />
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={!input.trim() || disabled}
            className={cn(
              "p-2 rounded-lg bg-primary text-primary-foreground",
              "hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
            )}
            title="Send"
          >
            <Send className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  )
}
