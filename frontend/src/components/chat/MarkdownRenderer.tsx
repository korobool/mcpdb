import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        // Style tables
        table: ({ children }) => (
          <div className="overflow-x-auto my-2">
            <table className="w-full">{children}</table>
          </div>
        ),
        // Code blocks
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
        // Links
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
