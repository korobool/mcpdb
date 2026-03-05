import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { MermaidBlock } from './MermaidBlock'

// Split markdown into alternating text/mermaid segments so mermaid blocks
// bypass rehype-highlight entirely (which strips unknown language classes).
const MERMAID_RE = /```mermaid\s*\n([\s\S]*?)```/g

interface Segment {
  type: 'md' | 'mermaid'
  content: string
}

function splitMermaid(content: string): Segment[] {
  const segments: Segment[] = []
  let last = 0
  let match: RegExpExecArray | null
  while ((match = MERMAID_RE.exec(content)) !== null) {
    if (match.index > last) {
      segments.push({ type: 'md', content: content.slice(last, match.index) })
    }
    segments.push({ type: 'mermaid', content: match[1].trim() })
    last = match.index + match[0].length
  }
  if (last < content.length) {
    segments.push({ type: 'md', content: content.slice(last) })
  }
  return segments.length ? segments : [{ type: 'md', content }]
}

export function MarkdownRenderer({ content }: { content: string }) {
  const segments = splitMermaid(content)

  return (
    <>
      {segments.map((seg, i) =>
        seg.type === 'mermaid' ? (
          <MermaidBlock key={i} code={seg.content} />
        ) : (
          <MarkdownSegment key={i} content={seg.content} />
        )
      )}
    </>
  )
}

function MarkdownSegment({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[[rehypeHighlight, { ignoreMissing: true }]]}
      components={{
        table: ({ children }) => (
          <div className="overflow-x-auto my-2">
            <table className="w-full">{children}</table>
          </div>
        ),
        pre: ({ children }) => (
          <pre className="overflow-x-auto rounded-md p-3 my-2 bg-muted text-sm">
            {children}
          </pre>
        ),
        code: ({ className, children, ...props }) => {
          const isInline = !className
          if (isInline) {
            return (
              <code className="px-1 py-0.5 rounded bg-muted text-sm" {...props}>
                {children}
              </code>
            )
          }
          return <code className={className} {...props}>{children}</code>
        },
        a: ({ children, href }) => (
          <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline">
            {children}
          </a>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
