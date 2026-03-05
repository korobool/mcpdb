import { useState, useRef } from 'react'
import { Database, FileSpreadsheet, FileText, Plus, X, Upload, Loader2 } from 'lucide-react'
import { useSourceStore } from '@/stores/sourceStore'
import { cn } from '@/lib/utils'

export function SourcePanel() {
  const { sources, loading, error, connectDatabase, uploadCSV, uploadExcel, removeSource } = useSourceStore()
  const [showConnect, setShowConnect] = useState(false)
  const [connStr, setConnStr] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [connectError, setConnectError] = useState('')
  const csvRef = useRef<HTMLInputElement>(null)
  const excelRef = useRef<HTMLInputElement>(null)

  const handleConnect = async () => {
    if (!connStr.trim()) return
    setConnectError('')
    try {
      await connectDatabase(connStr.trim(), displayName.trim() || undefined)
      setConnStr('')
      setDisplayName('')
      setShowConnect(false)
    } catch (e) {
      setConnectError((e as Error).message)
    }
  }

  const handleFileUpload = async (file: File, type: 'csv' | 'excel') => {
    try {
      if (type === 'csv') await uploadCSV(file)
      else await uploadExcel(file)
    } catch { /* error is in store */ }
  }

  const sourceIcon = (type: string) => {
    switch (type) {
      case 'database': return <Database className="w-4 h-4 text-blue-500" />
      case 'csv': return <FileText className="w-4 h-4 text-green-500" />
      case 'excel': return <FileSpreadsheet className="w-4 h-4 text-emerald-500" />
      default: return <Database className="w-4 h-4" />
    }
  }

  return (
    <div className="border-b border-sidebar-border">
      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-xs font-medium uppercase text-muted-foreground">Data Sources</span>
        <button
          onClick={() => setShowConnect(!showConnect)}
          className="p-1 hover:bg-muted rounded text-muted-foreground"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>

      {showConnect && (
        <div className="px-3 pb-3 space-y-2">
          <input
            type="text"
            placeholder="Connection string (e.g. sqlite:///data.db)"
            value={connStr}
            onChange={e => setConnStr(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleConnect()}
            className="w-full px-2 py-1.5 text-sm rounded border border-input bg-background"
          />
          <input
            type="text"
            placeholder="Display name (optional)"
            value={displayName}
            onChange={e => setDisplayName(e.target.value)}
            className="w-full px-2 py-1.5 text-sm rounded border border-input bg-background"
          />
          {connectError && (
            <p className="text-xs text-destructive">{connectError}</p>
          )}
          <div className="flex gap-2">
            <button
              onClick={handleConnect}
              disabled={loading || !connStr.trim()}
              className={cn(
                "flex-1 px-2 py-1.5 text-sm rounded bg-primary text-primary-foreground",
                "hover:opacity-90 disabled:opacity-50"
              )}
            >
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin mx-auto" /> : 'Connect'}
            </button>
          </div>

          <div className="flex gap-2 pt-1">
            <input ref={csvRef} type="file" accept=".csv" className="hidden"
              onChange={e => e.target.files?.[0] && handleFileUpload(e.target.files[0], 'csv')} />
            <input ref={excelRef} type="file" accept=".xlsx,.xls" className="hidden"
              onChange={e => e.target.files?.[0] && handleFileUpload(e.target.files[0], 'excel')} />
            <button
              onClick={() => csvRef.current?.click()}
              className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs rounded border border-input hover:bg-muted"
            >
              <Upload className="w-3 h-3" /> CSV
            </button>
            <button
              onClick={() => excelRef.current?.click()}
              className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs rounded border border-input hover:bg-muted"
            >
              <Upload className="w-3 h-3" /> Excel
            </button>
          </div>
        </div>
      )}

      {error && <p className="px-3 pb-2 text-xs text-destructive">{error}</p>}

      <div className="px-2 pb-2">
        {sources.length === 0 ? (
          <p className="text-xs text-muted-foreground px-1 py-2">No sources connected</p>
        ) : (
          sources.map(src => (
            <div
              key={src.source_id}
              className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted group"
            >
              {sourceIcon(src.source_type)}
              <div className="flex-1 min-w-0">
                <div className="text-sm truncate">{src.display_name}</div>
                <div className="text-xs text-muted-foreground">
                  {src.tables.length} table{src.tables.length !== 1 ? 's' : ''}
                </div>
              </div>
              <button
                onClick={() => removeSource(src.source_id)}
                className="p-1 opacity-0 group-hover:opacity-100 hover:bg-destructive/10 rounded text-destructive"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
