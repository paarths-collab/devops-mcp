# System Workflow & Logic — Observable Agent Control Panel

This document details the end-to-end operational workflow of the system, from initial user query to automated self-healing and deep failure diagnosis.

## 1. High-Level Component Map

The project is architecturally split into two halves: the **Executing Agent** (Monitored) and the **Control Panel** (Monitor).

```mermaid
graph TB
    subgraph "👤 Engineer / IDE Agent"
        Q["User Query / Audit Request"]
    end

    subgraph "🔍 Observable Agent Panel (The Monitor)"
        direction TB
        SRV["server.py<br/>MCP Entry Point"]
        ANA["analyzer.py<br/>Deep Diagnostic Engine"]
        TDB["trace_db.py<br/>SQLite Trace Store"]
    end

    subgraph "🤖 DevOps Agent (The Monitored System)"
        direction TB
        ORCH["orchestrator.py<br/>Repo-Aware Reasoning"]
        LTM["long_term.py<br/>Scoped Semantic Memory"]
        REG["registry.py<br/>Tool Dispatcher"]
    end

    subgraph "💾 Persistence"
        DB1[(memory.db<br/>Facts & Embeddings)]
        DB2[(traces.db<br/>Audit/Run Logs)]
    end

    Q -->|"MCP tool call (Traced)"| SRV
    SRV -->|"deep_diagnose_failures"| ANA
    SRV -->|"get_recent_traces"| TDB
    SRV -->|"search_memory"| LTM
    SRV -->|"execute_tool"| REG
    ORCH -->|"Decision Logging"| TDB
    LTM --> DB1
    TDB --> DB2
    ANA -->|"LLM Analysis"| Q
```

## 2. The Decision Workflow (Knowledge Boundary)

The `Orchestrator` uses a "Token-Optimized" decision tree with strict knowledge scoping to prevent hallucinations and infinite loops.

```mermaid
flowchart TD
    Start([User Query]) --> Triage{Semantic Search}
    Triage -- "Confidence > 0.8" --> Memory[Answer from Memory]
    Triage -- "Confidence < 0.8" --> ScopeCheck{Repo Indexed?}
    
    ScopeCheck -- "No" --> Stop[Stop & Inform: 'Repo Unindexed']
    ScopeCheck -- "Yes" --> Tooling[Enter Tooling Loop]
    
    Tooling --> Search[GitHub/Stack/Log Search]
    Search -- "Empty result for unknown repo" --> Stop
    Search -- "Success" --> LLM[LLM Reasoning & Synthesis]
    
    Memory --> Log[Write Trace to SQLite]
    LLM --> Log
    Log --> Outcome{Final Answer}
```

## 3. The Self-Healing Workflow (Deep Analysis)

When multiple runs fail or performance degrades, the system triggers an LLM-powered deep dive:

```mermaid
sequenceDiagram
    participant IDE as IDE Agent
    participant MCP as MCP Server
    participant Ana as Analyzer (LLM)
    participant DB as Trace DB
    
    IDE->>MCP: get_failure_candidates()
    MCP-->>IDE: List of failed run IDs
    
    IDE->>MCP: deep_diagnose_failures(id1, id2)
    MCP->>Ana: Fetch traces & analyze patterns
    Ana->>DB: Retrieve full hop history
    DB-->>Ana: Tool calls, results, latency
    Ana-->>MCP: [SUMMARY] | [ROOT CAUSE] | [STACK SEARCHES]
    MCP-->>IDE: Synthesized Diagnostic Report
    
    IDE->>MCP: search_stackexchange(suggested_query)
```

## 4. Operational Modes & Advanced Commands

| Mode | Command | Best For |
|---|---|---|
| **CLI (REPL)** | `python -m devops_agent.main --mode cli` | Interactive use, debugging, and real-time observability. |
| **Server (MCP)** | `python -m devops_agent.main --mode server` | Cursor/Antigravity integration with automatic trace logging. |

### Diagnostic Commands (REPL & Shell)
- **`--traces [N]`**: List the last N run IDs and their outcomes.
- **`--explain <ID>`**: Render the agent's internal reasoning as Markdown.
- **`--compare <ID1> <ID2>`**: Side-by-side structural comparison of two runs.
- **`--deep-analyze <IDs>`**: (New) LLM-powered pattern analysis across multiple failures.

## 5. Visibility & Persistence

*   **MCP Tracing**: Every tool call made by the IDE (e.g., `search_memory`) is now automatically recorded as a trace.
*   **`data/memory.db`**: Stores vector-based semantic facts (PRs, Issues).
*   **`data/traces.db`**: Stores every step taken by the agent for later auditing.
*   **`.env`**: Holds `GROQ_API_KEY`, `GITHUB_TOKEN`, and `HF_TOKEN`.
