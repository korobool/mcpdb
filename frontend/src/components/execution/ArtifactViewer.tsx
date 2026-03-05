import { useState } from 'react'
import { useChatStore, type Artifact } from '@/stores/chatStore'
import { MermaidBlock } from '@/components/chat/MermaidBlock'
import { FileText, Table2, BarChart3, GitBranch, ChevronDown, ChevronRight, Copy, Check } from 'lucide-react'
import { cn } from '@/lib/utils'

export function ArtifactViewer() {
  const messages = useChatStore(s => s.messages)

  // Get the last assistant message with artifacts
  const lastAssistant = [...messages].reverse().find(
    m => m.role === 'assistant' && m.artifacts && m.artifacts.length > 0
  )

  if (!lastAssistant?.artifacts?.length) {
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

  return (
    <div className="px-3 py-2">
      <div className="flex items-center gap-2 mb-2">
        <FileText className="w-3.5 h-3.5 text-muted-foreground" />
        <span className="text-xs font-medium uppercase text-muted-foreground">
          Artifacts ({lastAssistant.artifacts.length})
        </span>
      </div>
      <div className="space-y-2">
        {lastAssistant.artifacts.map((artifact, i) => (
          <ArtifactCard key={i} artifact={artifact} defaultOpen={i === 0} />
        ))}
      </div>
    </div>
  )
}

function ArtifactCard({ artifact, defaultOpen }: { artifact: Artifact; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const [copied, setCopied] = useState(false)

  const iconMap = {
    mermaid: GitBranch,
    code: artifact.language === 'sql' ? Table2 : BarChart3,
    table: Table2,
    log: FileText,
  }
  const Icon = iconMap[artifact.type] || FileText

  const handleCopy = () => {
    navigator.clipboard.writeText(artifact.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="rounded border border-border overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 w-full px-2 py-1.5 bg-muted text-xs hover:bg-muted/80"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <Icon className="w-3 h-3" />
        <span className="font-medium">{artifact.title}</span>
        <span className="ml-auto text-[10px] text-muted-foreground uppercase">{artifact.type}</span>
      </button>

      {open && (
        <div className="relative">
          <button
            onClick={handleCopy}
            className="absolute top-1 right-1 p-1 rounded hover:bg-muted text-muted-foreground z-10"
            title="Copy"
          >
            {copied ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
          </button>

          {artifact.type === 'mermaid' ? (
            <div className="p-2 overflow-x-auto">
              <MermaidBlock code={artifact.content} />
            </div>
          ) : (
            <pre className="px-2 py-1.5 text-[11px] bg-card overflow-x-auto max-h-[200px]">
              <code>{artifact.content}</code>
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
