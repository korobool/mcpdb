import { create } from 'zustand'
import type { QueryMode, WsIncoming } from '@/types/api'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  queryMode?: string
  artifacts?: Record<string, unknown>[]
  executionLog?: Record<string, unknown>[]
}

export interface ExecutionStep {
  event_type: string
  data: Record<string, unknown>
  timestamp: number
}

interface ChatState {
  messages: ChatMessage[]
  executionEvents: ExecutionStep[]
  isQuerying: boolean
  currentPhase: string
  ws: WebSocket | null

  connect: () => void
  disconnect: () => void
  sendQuery: (question: string, modeOverride?: QueryMode) => void
  cancelQuery: () => void
  clearMessages: () => void
}

let msgId = 0

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  executionEvents: [],
  isQuerying: false,
  currentPhase: '',
  ws: null,

  connect: () => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/query`)

    ws.onmessage = (evt) => {
      const msg: WsIncoming = JSON.parse(evt.data)

      if (msg.type === 'event') {
        const phase = _phaseLabel(msg.event_type, msg.data)
        set(s => ({
          executionEvents: [...s.executionEvents, {
            event_type: msg.event_type,
            data: msg.data,
            timestamp: msg.timestamp,
          }],
          currentPhase: phase || s.currentPhase,
        }))
      } else if (msg.type === 'result') {
        set(s => ({
          messages: [...s.messages, {
            id: String(++msgId),
            role: 'assistant',
            content: msg.response,
            timestamp: Date.now(),
            queryMode: msg.query_mode,
            artifacts: msg.artifacts,
            executionLog: msg.execution_log,
          }],
          isQuerying: false,
          currentPhase: '',
        }))
      } else if (msg.type === 'error') {
        set(s => ({
          messages: [...s.messages, {
            id: String(++msgId),
            role: 'system',
            content: `Error: ${msg.message}`,
            timestamp: Date.now(),
          }],
          isQuerying: false,
          currentPhase: '',
        }))
      } else if (msg.type === 'cancelled') {
        set({ isQuerying: false, currentPhase: '' })
      }
    }

    ws.onclose = () => {
      set({ ws: null })
      // Auto-reconnect after 2s
      setTimeout(() => {
        if (!get().ws) get().connect()
      }, 2000)
    }

    set({ ws })
  },

  disconnect: () => {
    get().ws?.close()
    set({ ws: null })
  },

  sendQuery: (question, modeOverride) => {
    const { ws } = get()
    if (!ws || ws.readyState !== WebSocket.OPEN) return

    // Add user message
    set(s => ({
      messages: [...s.messages, {
        id: String(++msgId),
        role: 'user',
        content: question,
        timestamp: Date.now(),
      }],
      executionEvents: [],
      isQuerying: true,
      currentPhase: 'Starting...',
    }))

    ws.send(JSON.stringify({
      type: 'query',
      question,
      ...(modeOverride ? { mode_override: modeOverride } : {}),
    }))
  },

  cancelQuery: () => {
    const { ws } = get()
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'cancel' }))
    }
  },

  clearMessages: () => set({ messages: [], executionEvents: [] }),
}))

// Map event types to phase labels
function _phaseLabel(eventType: string, data: Record<string, unknown>): string | null {
  const map: Record<string, string | null> = {
    'classify/start': 'Classifying...',
    'classify/complete': `Mode: ${data.mode ?? ''}`,
    'plan/start': 'Planning...',
    'plan/ready': `Plan ready (${data.step_count ?? '?'} steps)`,
    'plan/retry': 'Retrying plan...',
    'step/start': `Step ${data.step_number ?? '?'}/${data.total ?? '?'} (${data.action ?? ''})`,
    'step/complete': null,
    'step/error': `Step ${data.step_number ?? '?'} error`,
    'debug/start': 'Debugging...',
    'debug/fixed': 'Fix applied',
    'checkpoint/start': 'Reviewing progress...',
    'synthesize/start': 'Synthesizing...',
    'synthesize/complete': null,
    'quick/start': 'Answering...',
    'quick/escalate': 'Escalating to full analysis...',
    'experience/cache_hit': 'Using cached result',
  }
  return map[eventType] ?? null
}
