import { useChatStore } from '@/stores/chatStore'
import { FileText, Table2, BarChart3 } from 'lucide-react'

export function ArtifactViewer() {
  const messages = useChatStore(s => s.messages)

  // Get the last assistant message with artifacts
  const lastAssistant = [...messages].reverse().find(
    m => m.role === 'assistant' && m.executionLog && m.executionLog.length > 0
  )

  if (!lastAssistant?.executionLog?.length) {
    return (
      <div className="px-3 py-2">
        <div className="flex items-center gap-2 mb-2">
          <FileText className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs font-medium uppercase text-muted-foreground">Artifacts</span>
        </div>
        <p className="text-xs text-muted-foreground">No artifacts yet</p>
      </div>
    )
  }

  const log = lastAssistant.executionLog

  return (
    <div className="px-3 py-2">
      <div className="flex items-center gap-2 mb-2">
        <FileText className="w-3.5 h-3.5 text-muted-foreground" />
        <span className="text-xs font-medium uppercase text-muted-foreground">
          Execution Log ({log.length} step{log.length !== 1 ? 's' : ''})
        </span>
      </div>
      <div className="space-y-2">
        {log.map((entry, i) => (
          <LogEntry key={i} entry={entry} index={i} />
        ))}
      </div>
    </div>
  )
}

function LogEntry({ entry, index }: { entry: Record<string, unknown>; index: number }) {
  const action = String(entry.action_type || entry.action || 'unknown')
  const code = String(entry.code || '')
  const preview = String(entry.result_preview || '')
  const timeMs = Number(entry.time_ms || 0)
  const status = String(entry.status || 'success')

  const icon = action === 'sql' ? Table2 : action === 'python' ? BarChart3 : FileText
  const Icon = icon

  return (
    <div className="rounded border border-border overflow-hidden">
      <div className="flex items-center gap-2 px-2 py-1 bg-muted text-xs">
        <Icon className="w-3 h-3" />
        <span className="font-medium">Step {index + 1}: {action}</span>
        {timeMs > 0 && (
          <span className="ml-auto text-muted-foreground">{timeMs}ms</span>
        )}
        <span className={status === 'error' ? 'text-destructive' : 'text-green-500'}>
          {status}
        </span>
      </div>
      {code && (
        <pre className="px-2 py-1.5 text-[11px] bg-card overflow-x-auto max-h-[100px]">
          <code>{code}</code>
        </pre>
      )}
      {preview && (
        <div className="px-2 py-1 text-[11px] text-muted-foreground border-t border-border max-h-[80px] overflow-auto whitespace-pre">
          {preview.slice(0, 500)}
        </div>
      )}
    </div>
  )
}
