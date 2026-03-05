import { useRef, useEffect } from 'react'
import { useChatStore, type ChatMessage } from '@/stores/chatStore'
import { MarkdownRenderer } from './MarkdownRenderer'
import { User, Bot, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { motion, AnimatePresence } from 'framer-motion'

export function MessageList() {
  const messages = useChatStore(s => s.messages)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center text-muted-foreground max-w-md">
          <Bot className="w-12 h-12 mx-auto mb-4 opacity-30" />
          <h2 className="text-lg font-medium mb-2">Ask a question about your data</h2>
          <p className="text-sm">
            Connect a database, CSV, or Excel file, then ask questions in natural language.
            The AI will analyze your data and provide insights.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
      <AnimatePresence initial={false}>
        {messages.map(msg => (
          <Message key={msg.id} message={msg} />
        ))}
      </AnimatePresence>
      <div ref={bottomRef} />
    </div>
  )
}

function Message({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user'
  const isError = message.role === 'system'

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn(
        "flex gap-3",
        isUser && "justify-end"
      )}
    >
      {!isUser && (
        <div className={cn(
          "w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-1",
          isError ? "bg-destructive/10" : "bg-primary/10"
        )}>
          {isError ? (
            <AlertCircle className="w-4 h-4 text-destructive" />
          ) : (
            <Bot className="w-4 h-4 text-primary" />
          )}
        </div>
      )}

      <div className={cn(
        "max-w-[80%] rounded-lg px-4 py-3",
        isUser
          ? "bg-primary text-primary-foreground"
          : isError
            ? "bg-destructive/10 text-destructive"
            : "bg-muted"
      )}>
        {isUser ? (
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="markdown-body text-sm">
            <MarkdownRenderer content={message.content} />
          </div>
        )}
        {message.queryMode && (
          <div className="mt-2 flex items-center gap-2">
            <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-background/50 text-muted-foreground">
              {message.queryMode}
            </span>
          </div>
        )}
      </div>

      {isUser && (
        <div className="w-7 h-7 rounded-full bg-secondary flex items-center justify-center shrink-0 mt-1">
          <User className="w-4 h-4" />
        </div>
      )}
    </motion.div>
  )
}
