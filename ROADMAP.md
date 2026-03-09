# MCPDB Roadmap

> Current version: **5.3.0** | Last updated: 2026-03-09

This document outlines planned improvements and future directions for MCPDB. Items are organized by priority and grouped thematically.

---

## Milestone 1: Release Infrastructure

Get the basics right for sustainable open-source development.

### CI/CD Pipeline
- [ ] GitHub Actions: run tests on push/PR (pytest, lint)
- [ ] Automated PyPI publishing on tag/release
- [ ] Semantic versioning with changelog generation
- [ ] Branch protection rules for `main`

### Containerization
- [ ] Multi-stage Dockerfile (slim production image)
- [ ] `docker-compose.yml` with mcpdb + sample Postgres database
- [ ] One-command deployment: `docker run -e GEMINI_API_KEY=... mcpdb web`

### Documentation Site
- [ ] MkDocs or Sphinx site with full API reference
- [ ] Deployment guide (Docker, bare metal, cloud platforms)
- [ ] Troubleshooting / FAQ
- [ ] CHANGELOG (auto-generated from commits)

---

## Milestone 2: Data Sources & Connectors

Expand beyond SQL databases and flat files.

### New File Formats
- [ ] **Parquet** files (read via DuckDB, zero-copy)
- [ ] **JSON / JSONL** files (auto-detect schema, nested flattening)
- [ ] **Google Sheets** (via service account or OAuth)

### Cloud Data Warehouses
- [ ] **BigQuery** connector (google-cloud-bigquery)
- [ ] **Snowflake** connector (snowflake-connector-python)
- [ ] **Redshift** (via psycopg2 with Redshift dialect)
- [ ] **Databricks** SQL connector

### NoSQL
- [ ] **MongoDB** (read-only query translation: NL → aggregation pipeline)
- [ ] **DynamoDB** (scan/query abstraction)

### In-Memory Data
- [ ] Register a pandas DataFrame directly as a source (no file needed)
- [ ] Register a DuckDB connection as a source

---

## Milestone 3: Web Client Improvements

### Persistence & History
- [ ] Saved conversations (survive page refresh, stored server-side)
- [ ] Conversation list / history sidebar
- [ ] Resume previous analysis sessions
- [ ] Bookmarkable query URLs

### UX Polish
- [ ] Light / dark theme toggle
- [ ] Keyboard shortcuts (Ctrl+Enter to send, Esc to cancel, etc.)
- [ ] Query templates / snippets (common analysis patterns)
- [ ] Source search / filter in sidebar
- [ ] Interactive charts (Plotly instead of static matplotlib images)
- [ ] Mobile-optimized layout

### Collaboration
- [ ] Shareable read-only links to exported reports
- [ ] Multi-user sessions with authentication (OAuth / API key)
- [ ] Audit log of queries and results

---

## Milestone 4: LLM & Agent Improvements

### Provider Expansion
- [ ] **Azure OpenAI** endpoint support
- [ ] **Vertex AI** (Gemini via Google Cloud)
- [ ] **Mistral** provider
- [ ] **Local GGUF models** via llama-cpp-python (beyond Ollama)

### Agent Capabilities
- [ ] **Streaming synthesis** — token-by-token output in web UI and CLI
- [ ] **Multi-model routing** — fast model for classification, powerful model for planning
- [ ] **Controlled write operations** — INSERT/UPDATE with explicit approval gates
- [ ] **SQL audit trail** — log every generated query with explain plan
- [ ] **Schema auto-refresh** — detect schema changes without reconnecting

### Cost Management
- [ ] Per-query cost tracking (tokens used, estimated cost per provider)
- [ ] Budget alerts and limits per session / per day
- [ ] Provider cost comparison dashboard

---

## Milestone 5: Enterprise & Operations

### Security & Access Control
- [ ] Role-based access control (RBAC) — admin, analyst, viewer
- [ ] Per-source access policies (who can query what)
- [ ] Connection string vault integration (HashiCorp Vault, AWS Secrets Manager)

### Observability
- [ ] Health check endpoint (`/health`, `/ready`)
- [ ] Prometheus metrics export (query latency, LLM call count, cache hit rate)
- [ ] Structured JSON logging for log aggregation
- [ ] OpenTelemetry distributed tracing

### Scalability
- [ ] Horizontal scaling — multiple web workers behind a load balancer
- [ ] Redis-backed session storage (replace in-memory state)
- [ ] Connection pool tuning per database dialect
- [ ] Background job queue for long-running deep analyses

---

## Milestone 6: Automation & Integration

### Scheduled Queries & Reports
- [ ] Cron-style query scheduling (daily/weekly automated reports)
- [ ] Email/Slack delivery of results
- [ ] Data quality alerts (threshold monitoring, anomaly detection)

### REST API
- [ ] OpenAPI-documented REST API alongside MCP
- [ ] Python SDK for programmatic access (`from mcpdb import Client`)
- [ ] Webhook notifications on query completion

### Plugin System
- [ ] Custom data source plugins (register new source types)
- [ ] Custom analysis tools (user-defined MCP tools)
- [ ] Custom LLM providers (bring your own model)

---

## Technical Debt

Items to address alongside feature work:

- [ ] Extract `index.html` (~2000 lines) into separate CSS/JS files
- [ ] Add Pydantic request validation to all web API endpoints
- [ ] Migrate experience cache from JSONL to SQLite for structured queries
- [ ] Add integration tests against real databases (Postgres, MySQL) in CI
- [ ] Performance benchmarks (response time, memory, concurrent users)
- [ ] Browser compatibility testing (Firefox, Safari, Edge)
- [ ] Accessibility audit (WCAG 2.1 AA)

---

## Completed (v5.0–v5.3)

For reference, major features already shipped:

- Web client with real-time execution monitor (v5.1)
- Rich terminal UI + REPL + Textual TUI (v5.2)
- Export to HTML, PDF, Jupyter notebooks (v5.3)
- CSV/Excel as queryable sources with DuckDB federation
- 5 query modes with auto-classification
- Async reasoning observer with cancellation
- Experience cache with semantic similarity
- Production hardening (timeouts, sandboxing, XSS protection)
- 33 MCP tools across 10 categories
- 4 LLM providers (Gemini, OpenAI, Anthropic, Ollama)
- 1089 passing tests
