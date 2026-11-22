# PartnerScout architecture

```mermaid
flowchart TD
    U[Partnership request<br/>natural language or structured] --> O

    subgraph ORCH[Orchestrator: pipeline.py]
      O[Understand request -> structured brief<br/>plan, ceilings, retries, checkpoints]
    end

    O --> D[Agent 1 - Partner Discovery<br/>ranked company search, duplicate resolution, relevance screen]
    D --> I[Agent 2 - Company Intelligence<br/>identify, enrich, first-party site, news and adverse search]
    I --> V[Agent 3 - Trust and Verification<br/>quote-verified claims, contradictions, identity checks]
    V --> F[Agent 4 - Strategic Fit<br/>scores, competitive conflict, mutual value]
    F --> S[Agent 5 - Partnership Strategist<br/>model, stakeholder, proposal DRAFT]
    S --> R[Ranked report HTML + Streamlit UI]
    R --> H{{Human approval gate<br/>records intent, sends nothing}}

    subgraph CD[Crustdata API - via one client]
      C1[/company/search/]
      C2[/company/identify/]
      C3[/company/enrich: basic, headcount, funding, people/]
      C4[/web/search/live/]
      C5[/web/enrich/live: fetch page/]
    end
    D --- C1
    I --- C2
    I --- C3
    I --- C4
    I --- C5

    subgraph DB[SQLite]
      L[(call ledger: credits, model cost, latency)]
      K[(response cache)]
      P[(stage checkpoints: resume)]
      E[(evidence ledger)]
    end
    CD -.every call.-> L
    CD -.-> K
    ORCH -.-> P
    V --> E
    LLM[Gemini - one shared model, five role prompts] -.-> L
```

Rules enforced in code, not just in prompts:

* A claim is **verified** only if its quote appears in the cited source text (`evidence.py`).
* Unknown is never zero: missing components are dropped and weights renormalised (`scoring.py`).
* Hard flags (identity unresolved, contradictions) override the numeric score.
* Every Crustdata and model call is logged; each run has a credit and a time ceiling.
* Every stage is checkpointed per (run, stage, item); a restart never repeats a paid call.
