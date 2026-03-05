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

let counter = 0

export function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [svg, setSvg] = useState<string>('')
  const [error, setError] = useState<string>('')
  const idRef = useRef(`mermaid-${++counter}`)

  useEffect(() => {
    const dark = document.documentElement.classList.contains('dark')
    ensureInit(dark)

    let cancelled = false
    mermaid.render(idRef.current, code.trim()).then(
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
