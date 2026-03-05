import { useState } from 'react'
import { ExecutionMonitor } from '@/components/execution/ExecutionMonitor'
import { ArtifactViewer } from '@/components/execution/ArtifactViewer'
import { ChevronLeft, ChevronRight } from 'lucide-react'

export function RightSidebar() {
  const [collapsed, setCollapsed] = useState(false)

  if (collapsed) {
    return (
      <div className="w-10 border-l border-border bg-sidebar flex flex-col items-center pt-2">
        <button onClick={() => setCollapsed(false)} className="p-1 hover:bg-muted rounded">
          <ChevronLeft className="w-4 h-4" />
        </button>
      </div>
    )
  }

  return (
    <aside className="w-80 border-l border-sidebar-border bg-sidebar flex flex-col overflow-hidden shrink-0">
      <div className="flex items-center justify-between px-3 py-2 border-b border-sidebar-border">
        <span className="text-sm font-medium text-sidebar-foreground">Execution</span>
        <button onClick={() => setCollapsed(true)} className="p-1 hover:bg-muted rounded">
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        <ExecutionMonitor />
        <ArtifactViewer />
      </div>
    </aside>
  )
}
