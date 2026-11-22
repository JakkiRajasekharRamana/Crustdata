# PartnerScout architecture

The same architecture, technical and business, is on one editable draw.io page (link in the README). This file is the Mermaid version of the technical part.

```mermaid
flowchart TD
    U[Partnership request<br/>free text and optional structured fields] --> VAL

    VAL[validation.py<br/>rejects or asks for clarification<br/>before any model or paid call] --> O

    subgraph ORCH[pipeline.py: orchestrator, every stage checkpointed in SQLite]
      O[1 Understand request<br/>Gemini -> structured brief] --> D[2 Discover<br/>3 ranked company searches, duplicates collapsed]
      D --> RK[3 Rank - ranking.py<br/>code-computed prescore for every candidate<br/>model gives categorical judgements at temperature 0]
      RK --> I[4 Investigate<br/>identity, enrichment, own website, news and adverse media<br/>Person Search only when no decision-maker is listed]
      I --> V[5 Verify - evidence.py<br/>verbatim quote must exist in its source<br/>sources classified, redirects resolved, conflicts need two quotes]
      V --> F[6 Evaluate - scoring.py<br/>5-part fit, conflict penalty, relationship dimensions<br/>mutual value, evidence confidence kept separate]
      F --> S[7 Recommend<br/>ranked brief, partnership model, decision-maker, draft message]
    end

    S --> R[report.py<br/>self-contained HTML report]
    S --> H{{Human approval gate<br/>records a decision only; nothing is sent}}

    subgraph CD[Crustdata API - only through crustdata.py]
      C1[/company/search/]
      C2[/company/identify/]
      C3[/company/enrich/]
      C4[/person/search/]
      C5[/web/enrich/live/]
      C6[/web/search/live/]
    end
    D --- C1
    I --- C2
    I --- C3
    I --- C4
    I --- C5
    I --- C6

    subgraph CLIENT[crustdata.py and llm.py]
      K1[per-endpoint rate limits read from /account/endpoints]
      K2[credit and time ceilings checked before every call]
      K3[bounded retries, 429 honours x-ratelimit-reset, 402 stops the run]
      K4[response cache and one ledger row per attempt]
    end
    CD --- CLIENT
    DB[(SQLite: call ledger, cache, stage checkpoints,<br/>evidence ledger, approvals, pipeline stages)]
    CLIENT --> DB
    ORCH --> DB
    UI[Streamlit app: Brief, Workspace, Ecosystem, Pipeline, Dashboard, Brief generator] --> DB
    UI --> U
```

Restart rule: `stage(run_id, stage, item, fn)` runs `fn` once per key and returns the stored output afterwards, so killing the process and starting it again with the same run id repeats no paid call.
