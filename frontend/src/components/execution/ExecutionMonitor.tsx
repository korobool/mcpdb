import { useChatStore, type ExecutionStep } from '@/stores/chatStore'
import { CheckCircle2, Circle, AlertCircle, Loader2, Activity } from 'lucide-react'
import { cn } from '@/lib/utils'
import { motion, AnimatePresence } from 'framer-motion'

const PHASE_LABELS: Record<string, string> = {
  'classify/start': 'Classifying',
  'classify/complete': 'Classified',
  'plan/start': 'Planning',
  'plan/ready': 'Plan ready',
  'plan/retry': 'Retrying plan',
  'step/start': 'Executing step',
  'step/complete': 'Step complete',
  'step/error': 'Step error',
  'debug/start': 'Debugging',
  'debug/fixed': 'Fix applied',
  'debug/give_up': 'Skipped step',
  'checkpoint/start': 'Checkpoint',
  'checkpoint/complete': 'Checkpoint done',
  'revise/start': 'Revising plan',
  'synthesize/start': 'Synthesizing',
  'synthesize/complete': 'Complete',
  'quick/start': 'Quick answer',
  'quick/escalate': 'Escalating',
  'experience/cache_hit': 'Cache hit',
  'agent/complete': 'Done',
}

function stepIcon(eventType: string) {
  if (eventType.endsWith('/complete') || eventType === 'debug/fixed' || eventType === 'agent/complete') {
    return <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
  }
  if (eventType.endsWith('/error') || eventType === 'debug/give_up') {
    return <AlertCircle className="w-3.5 h-3.5 text-destructive" />
  }
  if (eventType.endsWith('/start')) {
    return <Loader2 className="w-3.5 h-3.5 text-primary animate-spin" />
  }
  return <Circle className="w-3.5 h-3.5 text-muted-foreground" />
}

export function ExecutionMonitor() {
  const { executionEvents, isQuerying, currentPhase } = useChatStore()

  return (
    <div className="border-b border-sidebar-border">
      <div className="flex items-center gap-2 px-3 py-2">
        <Activity className="w-3.5 h-3.5 text-muted-foreground" />
        <span className="text-xs font-medium uppercase text-muted-foreground">Activity</span>
        {isQuerying && (
          <span className="ml-auto flex items-center gap-1 text-xs text-primary">
            <Loader2 className="w-3 h-3 animate-spin" />
            Active
          </span>
        )}
      </div>

      {executionEvents.length === 0 && !isQuerying ? (
        <p className="px-3 pb-3 text-xs text-muted-foreground">No activity yet</p>
      ) : (
        <div className="px-3 pb-3 space-y-0.5 max-h-[400px] overflow-y-auto">
          <AnimatePresence initial={false}>
            {executionEvents.map((step, i) => (
              <StepRow key={i} step={step} />
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}

function StepRow({ step }: { step: ExecutionStep }) {
  const label = PHASE_LABELS[step.event_type] || step.event_type
  const detail = _detail(step)

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.15 }}
      className="flex items-start gap-2 py-1"
    >
      <div className="mt-0.5">{stepIcon(step.event_type)}</div>
      <div className="min-w-0">
        <div className="text-xs">{label}</div>
        {detail && <div className="text-[10px] text-muted-foreground truncate">{detail}</div>}
      </div>
    </motion.div>
  )
}

function _detail(step: ExecutionStep): string | null {
  const d = step.data
  if (step.event_type === 'classify/complete') return `Mode: ${d.mode ?? ''}`
  if (step.event_type === 'plan/ready') return `${d.step_count ?? '?'} steps planned`
  if (step.event_type === 'step/start') return `#${d.step_number ?? '?'} ${d.action ?? ''}: ${d.description ?? ''}`
  if (step.event_type === 'step/complete') return `${d.time_ms ?? 0}ms`
  if (step.event_type === 'step/error') return String(d.error ?? '').slice(0, 80)
  return null
}
