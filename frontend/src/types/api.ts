/* API types matching the FastAPI backend. */

export interface ColumnInfo {
  name: string
  dtype: string
  nullable: boolean
  description: string
}

export interface TableInfo {
  name: string
  columns: ColumnInfo[]
  row_count: number | null
  schema: string | null
  primary_keys: string[]
}

export interface SourceMetadata {
  source_id: string
  source_type: "database" | "csv" | "excel"
  display_name: string
  tables: TableInfo[]
  capabilities: string[]
  raw_info: Record<string, unknown>
}

export interface SampleData {
  columns: string[]
  rows: Record<string, unknown>[]
  total_rows: number
}

export interface HealthResponse {
  version: string
  source_count: number
  llm_provider: string
  llm_model: string
}

export interface LLMConfig {
  provider: string
  model: string
  has_key: boolean
}

export interface ProviderInfo {
  name: string
  display_name: string
  models: string[]
  env_key: string | null
}

// WebSocket message types
export type QueryMode = "quick" | "simple" | "extended" | "optimization_required" | "deep"

export interface WsQueryMessage {
  type: "query"
  question: string
  mode_override?: QueryMode
}

export interface WsCancelMessage {
  type: "cancel"
}

export interface WsEventMessage {
  type: "event"
  event_type: string
  data: Record<string, unknown>
  timestamp: number
}

export interface WsResultMessage {
  type: "result"
  response: string
  artifacts: Record<string, unknown>[]
  execution_log: Record<string, unknown>[]
  query_mode: string
}

export interface WsErrorMessage {
  type: "error"
  message: string
}

export type WsOutgoing = WsQueryMessage | WsCancelMessage
export type WsIncoming = WsEventMessage | WsResultMessage | WsErrorMessage | { type: "cancelled" }
