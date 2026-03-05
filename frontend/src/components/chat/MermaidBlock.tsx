import { useEffect, useRef, useState } from 'react'
import mermaid from 'mermaid'

let initialized = false

function ensureInit(dark: boolean) {
  mermaid.initialize({
    startOnLoad: false,
    theme: dark ? 'dark' : 'default',
    securityLevel: 'loose',
  })
  initialized = true
}

// Fix common LLM-generated mermaid issues before rendering.
// e.g. erDiagram attributes: "INTEGER id PK FK" → "INTEGER id PK,FK"
function sanitizeMermaid(code: string): string {
  const keys = ['PK', 'FK', 'UK']
  return code.replace(
    /^(\s+\w+\s+\w+)\s+((?:PK|FK|UK)(?:\s+(?:PK|FK|UK))+)\s*$/gm,
    (_match, prefix: string, attrs: string) => {
      const parts = attrs.split(/\s+/).filter((k: string) => keys.includes(k))
      return `${prefix} ${parts.join(',')}`
    },
  )
}

let counter = 0

export function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [svg, setSvg] = useState<string>('')
  const [error, setError] = useState<string>('')
  const idRef = useRef(`mermaid-${++counter}`)

  useEffect(() => {
    const dark = document.documentElement.classList.contains('dark')
    ensureInit(dark)

    const sanitized = sanitizeMermaid(code.trim())
    let cancelled = false
    mermaid.render(idRef.current, sanitized).then(
      ({ svg }) => { if (!cancelled) setSvg(svg) },
      (err) => { if (!cancelled) setError(String(err)) },
    )
    return () => { cancelled = true }
  }, [code])

  if (error) {
    return (
      <pre className="overflow-x-auto rounded-md p-3 my-2 bg-muted text-sm text-destructive">
        <code>{code}</code>
        <div className="mt-2 text-xs opacity-70">Mermaid error: {error}</div>
      </pre>
    )
  }

  if (!svg) {
    return <div className="p-3 my-2 text-sm text-muted-foreground">Rendering diagram...</div>
  }

  return (
    <div
      ref={ref}
      className="my-2 overflow-x-auto [&_svg]:max-w-full"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
