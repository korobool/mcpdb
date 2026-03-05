import { MessageList } from './MessageList'
import { ChatInput } from './ChatInput'
import { useChatStore } from '@/stores/chatStore'
import { useSourceStore } from '@/stores/sourceStore'

export function ChatArea() {
  const { isQuerying, currentPhase } = useChatStore()
  const sources = useSourceStore(s => s.sources)

  return (
    <main className="flex-1 flex flex-col min-w-0">
      <MessageList />
      {isQuerying && currentPhase && (
        <div className="px-4 py-1.5 text-sm text-muted-foreground border-t border-border bg-muted/30 flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full bg-primary animate-pulse" />
          {currentPhase}
        </div>
      )}
      {sources.length === 0 && (
        <div className="px-4 py-2 text-xs text-muted-foreground bg-muted/30 border-t border-border">
          Connect a data source in the left panel to start querying
        </div>
      )}
      <ChatInput />
    </main>
  )
}
