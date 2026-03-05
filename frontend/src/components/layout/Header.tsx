import { Database, Moon, Sun, Trash2 } from 'lucide-react'
import { useConfigStore } from '@/stores/configStore'
import { useChatStore } from '@/stores/chatStore'

export function Header() {
  const { theme, toggleTheme, llmConfig } = useConfigStore()
  const clearMessages = useChatStore(s => s.clearMessages)

  return (
    <header className="flex items-center justify-between px-4 py-2 border-b border-border bg-card">
      <div className="flex items-center gap-2">
        <Database className="w-5 h-5 text-primary" />
        <span className="font-semibold text-lg">MCPDB Playground</span>
        {llmConfig && (
          <span className="text-xs text-muted-foreground ml-2 px-2 py-0.5 bg-muted rounded">
            {llmConfig.provider}/{llmConfig.model}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={clearMessages}
          className="p-2 rounded-md hover:bg-muted text-muted-foreground"
          title="Clear chat"
        >
          <Trash2 className="w-4 h-4" />
        </button>
        <button
          onClick={toggleTheme}
          className="p-2 rounded-md hover:bg-muted text-muted-foreground"
          title="Toggle theme"
        >
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
      </div>
    </header>
  )
}
