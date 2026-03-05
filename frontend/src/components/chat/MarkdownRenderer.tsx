import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { MermaidBlock } from './MermaidBlock'

function extractText(children: unknown): string {
  if (typeof children === 'string') return children
  if (Array.isArray(children)) return children.map(extractText).join('')
  if (children && typeof children === 'object' && 'props' in (children as any)) {
    return extractText((children as any).props.children)
  }
  return ''
}

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        table: ({ children }) => (
          <div className="overflow-x-auto my-2">
            <table className="w-full">{children}</table>
          </div>
        ),
        pre: ({ children }) => {
          // Check if this is a mermaid code block
          const child = Array.isArray(children) ? children[0] : children
          if (child && typeof child === 'object' && 'props' in (child as any)) {
            const props = (child as any).props
            const className: string = props.className || ''
            if (className.includes('mermaid')) {
              const code = extractText(props.children)
              return <MermaidBlock code={code} />
            }
          }
          return (
            <pre className="overflow-x-auto rounded-md p-3 my-2 bg-muted text-sm">
              {children}
            </pre>
          )
        },
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
