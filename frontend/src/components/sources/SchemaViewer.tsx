import { useState } from 'react'
import { ChevronRight, ChevronDown, Table2, Columns3, Eye } from 'lucide-react'
import { useSourceStore } from '@/stores/sourceStore'
import type { TableInfo, ColumnInfo } from '@/types/api'
import { cn } from '@/lib/utils'

export function SchemaViewer() {
  const { sources, samples, fetchSample } = useSourceStore()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [sampleTable, setSampleTable] = useState<string | null>(null)

  const toggle = (key: string) => {
    const next = new Set(expanded)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    setExpanded(next)
  }

  if (sources.length === 0) return null

  const handleSample = (sourceId: string, table: string) => {
    const key = `${sourceId}:${table}`
    if (sampleTable === key) {
      setSampleTable(null)
      return
    }
    setSampleTable(key)
    if (!samples[key]) fetchSample(sourceId, table)
  }

  return (
    <div className="px-2 pb-2">
      <div className="px-1 py-2">
        <span className="text-xs font-medium uppercase text-muted-foreground">Schema</span>
      </div>
      {sources.map(src => (
        <div key={src.source_id}>
          <button
            onClick={() => toggle(src.source_id)}
            className="flex items-center gap-1 w-full px-1 py-1 text-sm hover:bg-muted rounded"
          >
            {expanded.has(src.source_id) ? (
              <ChevronDown className="w-3.5 h-3.5" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5" />
            )}
            <span className="truncate font-medium">{src.display_name}</span>
          </button>

          {expanded.has(src.source_id) && (
            <div className="ml-3">
              {src.tables.map(table => (
                <TableNode
                  key={table.name}
                  table={table}
                  sourceId={src.source_id}
                  expanded={expanded}
                  toggle={toggle}
                  onSample={() => handleSample(src.source_id, table.name)}
                  sampleData={sampleTable === `${src.source_id}:${table.name}` ? samples[`${src.source_id}:${table.name}`] : null}
                />
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function TableNode({
  table, sourceId, expanded, toggle, onSample, sampleData
}: {
  table: TableInfo
  sourceId: string
  expanded: Set<string>
  toggle: (k: string) => void
  onSample: () => void
  sampleData: { columns: string[]; rows: Record<string, unknown>[] } | null
}) {
  const key = `${sourceId}:${table.name}`
  const isOpen = expanded.has(key)

  return (
    <div>
      <div className="flex items-center group">
        <button
          onClick={() => toggle(key)}
          className="flex items-center gap-1 flex-1 px-1 py-0.5 text-sm hover:bg-muted rounded"
        >
          {isOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          <Table2 className="w-3 h-3 text-muted-foreground" />
          <span className="truncate">{table.name}</span>
          {table.row_count != null && (
            <span className="text-xs text-muted-foreground ml-auto">{table.row_count.toLocaleString()}</span>
          )}
        </button>
        <button
          onClick={onSample}
          className="p-0.5 opacity-0 group-hover:opacity-100 hover:bg-muted rounded text-muted-foreground"
          title="Preview data"
        >
          <Eye className="w-3 h-3" />
        </button>
      </div>

      {isOpen && (
        <div className="ml-5">
          {table.columns.map(col => (
            <ColumnNode key={col.name} column={col} isPK={table.primary_keys.includes(col.name)} />
          ))}
        </div>
      )}

      {sampleData && (
        <div className="ml-5 mt-1 mb-2 overflow-x-auto">
          <table className="text-xs border-collapse w-full">
            <thead>
              <tr>
                {sampleData.columns.map(c => (
                  <th key={c} className="border border-border px-2 py-1 bg-muted text-left font-medium">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sampleData.rows.slice(0, 5).map((row, i) => (
                <tr key={i}>
                  {sampleData.columns.map(c => (
                    <td key={c} className="border border-border px-2 py-0.5 truncate max-w-[120px]">
                      {String(row[c] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function ColumnNode({ column, isPK }: { column: ColumnInfo; isPK: boolean }) {
  return (
    <div className="flex items-center gap-1 px-1 py-0.5 text-xs text-muted-foreground">
      <Columns3 className="w-3 h-3" />
      <span className={cn(isPK && 'font-semibold text-foreground')}>
        {column.name}
      </span>
      <span className="ml-auto text-[10px] opacity-70">{column.dtype}</span>
      {isPK && <span className="text-[10px] text-primary font-medium">PK</span>}
    </div>
  )
}
