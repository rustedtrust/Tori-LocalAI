# Deep Research Technology Audit — 2026-08

**Project:** Tori
**Status:** Technology-selection audit; ready for human review
**Decision requested:** approve a standalone proof of concept, not a Deep Research V1 implementation contract
**Audit date:** 2026-08-29
**Repository baseline:** `main` at `f44e76f41cbdfedbae8681aeec725e32c4ce6985`

**Historical note:** This evaluates the earlier Deep Research experiment and its then-unproven POC. The later [Research Worker V1](../RESEARCH_WORKER_V1_ARCHITECTURE.md) is accepted; see [Current State](../FINAL_STATE.md) for its present deployment dependency. Recommendations below are dated evidence, not current install instructions.

## 1. Verdict

**Recommended primary candidate: GPT Researcher, conditionally.** It is the best current fit for a replaceable research-mechanics worker because it has a real Python package API, recursive breadth/depth research, programmatic source access, configurable model roles, generic OpenAI-compatible transport, Searx/SearXNG and no-key DuckDuckGo retrieval, academic retrievers, local-document modes, progress hooks, a local service implementation, an Apache-2.0 license, and active 2026 maintenance.

**Do not adopt GPT Researcher's bundled application as Tori architecture.** Tori should use the package behind a narrow, isolated worker wrapper. The bundled UI, report chat, file upload/delete routes, report store, environment-driven global configuration, memory/vector-store choices, and assistant-like presentation remain outside the boundary. Its current dependency set is heavy and includes Ollama packages even when Ollama is unused; its citations, cancellation, progress events, and restart behavior are not yet strong enough to accept without a POC.

**Recommended runner-up: LangChain Open Deep Research as a technical reference and fallback codebase, not as an unqualified dependency.** It has the strongest demonstrated research orchestration and benchmark evidence of the group, plus clean model-role separation, parallel research units, reflection loops, MCP tools, and LangGraph lifecycle facilities. However, GitHub states that its owner archived it on **2026-08-21** and made it read-only. That is a major, immediate maintenance concern. It should be selected only if a credible maintained successor or fork is identified and Tori accepts LangGraph coupling.

**A small standalone POC is warranted before the V1 contract.** The POC must not be placed in Tori or mutate Tori runtime. It should prove GPT Researcher with an LM Studio OpenAI-compatible endpoint, a no-paid-key retrieval path, narrow progress and cancellation events, raw evidence export, citation validation, dependency/runtime isolation, and clean process termination. Failure on the contract-level gates in section 15 should reopen selection between a maintained GPT Researcher adapter, a maintained successor/fork of Open Deep Research, and a smaller Tori-controlled workflow—not trigger broad vendoring.

## 2. Decision boundary

The required architecture is:

```text
Conversation / Projects / approved source context
                    |
                    v
          ResearchService (Tori)
                    |
                    v
             ResearchPort (Tori)
                    |
                    v
       isolated worker adapter / process
                    |
                    v
   replaceable open-source research mechanics
```

Tori owns identity, conversation, research intent and scope, authority, request admission, lifecycle truth, cancellation policy, Project/context integration, progress presentation, result acceptance, durable Tori-side records, final conversational synthesis, and any later user-approved promotion into Knowledge or Second Brain.

The worker owns query decomposition, research branches, search iteration, source retrieval, evidence collection, and synthesis inputs. It returns data and lifecycle evidence. It has no Tori identity, no independent authority, and no right to write canonical Tori state.

This audit does not approve an engine, dependency, schema, service, network endpoint, search provider, Knowledge ingestion path, or runtime mutation. It recommends the next evidence-gathering step.

## 3. Evidence method and confidence labels

The audit inspected Tori's accepted architecture/governance, current model and search ports, bounded source retrieval, Knowledge boundary, and candidate upstream repositories/documentation. It did not clone, install, configure, or run any candidate.

The following labels are used:

- **Verified current fact:** observed in authoritative upstream repository metadata, source, or official documentation on the audit date.
- **Upstream claim:** stated by the project but not reproduced in this audit.
- **Inference:** architectural conclusion from inspected interfaces and source.
- **POC unknown:** behavior that source inspection cannot establish reliably.

Repository activity timestamps indicate maintenance signal, not quality by themselves. Star and issue counts were inspected but are not used as selection scores.

## 4. Tori's existing fit

Tori already has several relevant replacement seams:

- a provider-neutral `ModelProvider` and an OpenAI-compatible adapter;
- a Tori-owned `SearchPort` and search consent/application policy;
- bounded `SourceRetrievalPort` behavior with untrusted-content treatment;
- application-side citation-marker and source-list validation;
- a narrow `KnowledgeRetrievalPort`; and
- explicit architecture governance requiring external tools to have capability but no authority.

The current Search contract explicitly excludes multi-step autonomous research. Deep Research therefore needs its own `ResearchPort`; it must not stretch a one-search operation into an implicit autonomous agent.

The eventual contract should normalize at least:

- request identity, accepted scope, source policy, model profile references, breadth/depth/time/token/source budgets, and deadline;
- lifecycle states and typed progress events;
- cancellation acknowledgement and terminal status;
- normalized queries, sources, retrieval timestamps, raw evidence metadata, findings, and final worker report;
- warnings, partial-result status, model/search configuration actually used, and reproducibility metadata; and
- an explicit distinction among worker output, Tori-accepted research artifacts, and user-curated Knowledge.

No candidate's native objects should cross this port unchanged.

## 5. Serious candidates evaluated

1. [GPT Researcher](https://github.com/assafelovic/gpt-researcher)
2. [LangChain Open Deep Research](https://github.com/langchain-ai/open_deep_research)
3. [Stanford STORM / Co-STORM](https://github.com/stanford-oval/storm)
4. [Hugging Face Open Deep Research / smolagents](https://github.com/huggingface/smolagents/tree/main/examples/open_deep_research)
5. [Jina AI node-DeepResearch](https://github.com/jina-ai/node-DeepResearch)

Jina was added because it is active in 2026, has a narrow local OpenAI-compatible HTTP surface, explicitly documents LM Studio transport, iterates search/read/reason until a budget is exhausted, and returns URL citation annotations. It materially tests whether a smaller service-shaped worker can beat a large Python stack. It does not do so for Tori V1 because it deliberately optimizes concise answers rather than long research reports and requires a Jina API key in the inspected local configuration.

`langchain-ai/local-deep-researcher` was screened but not promoted to the serious-candidate matrix. It is current and local-focused, but its defining workflow is Ollama-centric and therefore violates the provider-neutral invariant more directly than the candidates above. Other GitHub projects screened did not add a sufficiently differentiated, maintained, service-ready option to justify padding the matrix.

## 6. Decision matrix

Ratings describe fit for **Tori Deep Research V1**, not general project merit.

| Criterion | GPT Researcher | LangChain Open Deep Research | STORM / Co-STORM | HF ODR / smolagents | Jina node-DeepResearch |
|---|---|---|---|---|---|
| Provider neutrality | **Strong** | **Strong transport; Acceptable local-model fit** | **Acceptable** | **Strong library; Acceptable example** | **Strong transport** |
| LM Studio feasibility | **Strong transport; POC required** | **Acceptable; POC/high-capability model required** | **Acceptable via LiteLLM; undocumented path** | **Strong transport; example needs redesign** | **Strong and explicitly documented** |
| Search neutrality | **Strong** | **Acceptable** | **Strong** | **Weak** | **Weak** |
| Programmatic worker surface | **Strong** | **Strong if LangGraph adopted** | **Strong Python API** | **Weak as subsystem** | **Strong HTTP API** |
| General deep-research mechanics | **Strong** | **Strong** | **Acceptable, article/curation-shaped** | **Acceptable agent example** | **Acceptable, concise-answer-shaped** |
| Evidence and citation access | **Acceptable** | **Acceptable** | **Strong for article references** | **Weak** | **Acceptable** |
| Progress/control | **Acceptable** | **Strong through LangGraph runtime** | **Weak** | **Acceptable library, Weak example contract** | **Acceptable streaming, Weak lifecycle** |
| Cancellation | **Weak / POC required** | **Acceptable through LangGraph runtime** | **Weak** | **Weak** | **Weak / connection-scoped** |
| Durable restart/resume | **Weak** | **Acceptable to Strong if checkpointer/server is adopted** | **Acceptable stage artifacts, Weak run semantics** | **Weak** | **Weak** |
| Local/user documents | **Strong capability, authority wrapper required** | **Acceptable through MCP tools** | **Strong curation capability** | **Strong file tooling, unsafe default scope** | **Weak** |
| Dependency/operations cost | **Weak** | **Weak** | **Weak** | **Disqualifying concern for this example** | **Acceptable** |
| Maintenance health, 2026 | **Strong** | **Disqualifying concern: archived** | **Weak to Acceptable** | **Strong library; example not a product** | **Acceptable** |
| Security/authority fit | **Acceptable only behind wrapper** | **Acceptable with tool allowlist** | **Acceptable** | **Disqualifying concern as shipped** | **Acceptable with retrieval/network restrictions** |
| Replaceability | **Strong behind Tori port** | **Acceptable; LangGraph leaks if adopted broadly** | **Acceptable** | **Weak if Tori builds on framework internals** | **Strong HTTP seam, Weak retrieval independence** |
| Overall V1 fit | **Primary, conditional POC** | **Runner-up/reference only** | **Future curation/Second Brain candidate** | **Reference implementation only** | **Narrow fallback, not report worker** |

## 7. Candidate findings

### 7.1 GPT Researcher

#### Verified strengths

- The project provides the async `GPTResearcher` Python class with `conduct_research()`, `write_report()`, and getters for research context, costs, images, source URLs, and source records. The UI is not required. [Package documentation](https://docs.gptr.dev/docs/gpt-researcher/gptr/pip-package)
- `FAST_LLM`, `SMART_LLM`, and `STRATEGIC_LLM` are independently configurable. The current implementation parses provider/model strings and uses LangChain provider adapters. [Configuration documentation](https://docs.gptr.dev/docs/gpt-researcher/gptr/config)
- The OpenAI provider uses `langchain_openai.ChatOpenAI` and honors `OPENAI_BASE_URL`; embeddings can also use that base URL. Ollama has a separate branch and separate base URL. This means Ollama semantics are not architectural to the model path. [Model adapter source](https://github.com/assafelovic/gpt-researcher/blob/main/gpt_researcher/llm_provider/generic/base.py), [embedding source](https://github.com/assafelovic/gpt-researcher/blob/main/gpt_researcher/memory/embeddings.py)
- Current retrievers include Searx, DuckDuckGo, arXiv, OpenAlex, Semantic Scholar, PubMed Central, MCP, and a custom HTTP retriever alongside paid services. Multiple retrievers can be composed. [Search documentation](https://docs.gptr.dev/docs/gpt-researcher/search-engines/search-engines)
- Deep mode implements recursive breadth/depth exploration, concurrency limits, query generation, branch research, follow-up questions, accumulated learnings/context/sources, and a progress callback. [Deep Research source](https://github.com/assafelovic/gpt-researcher/blob/main/gpt_researcher/skills/deep_research.py)
- The class accepts explicit source URLs, document URLs, document objects, a vector store, preloaded context, and MCP configurations. Local-document documentation covers PDF, text, CSV, spreadsheet, Markdown, presentation, and Word files. [Local documents](https://docs.gptr.dev/docs/gpt-researcher/context/local-docs)
- A FastAPI/WebSocket implementation and log/event handlers exist. WebSocket disconnect cancels the connection's running asyncio task. The package also exposes direct Python callbacks. [Server source](https://github.com/assafelovic/gpt-researcher/tree/main/backend/server)
- GitHub reported the repository active and unarchived, with a latest release `v3.6.1` published 2026-08-24 and repository activity through 2026-08-27. License: Apache-2.0. [Releases](https://github.com/assafelovic/gpt-researcher/releases)

#### Material concerns

- The root requirements are heavy: FastAPI, LangChain/legacy/community/core, LangGraph, LiteLLM, OpenAI, Ollama and `langchain-ollama`, document processors, NumPy/Pandas, MCP, SQLAlchemy, PDF/Word output, and more. Ollama packages are direct requirements even though the OpenAI-compatible path does not use them. Dependency separation must be proven.
- The generic provider helper attempts to install a missing provider package at runtime. That is incompatible with Tori's runtime authority and offline expectations. The worker must run from a prebuilt, pinned venv with runtime package installation disabled or made impossible.
- Configuration is substantially environment/global-state driven. A multi-run service risks cross-run leakage unless the wrapper constructs per-run configuration or isolates each run in its own process.
- The bundled FastAPI application exposes UI, report chat, upload/delete routes, output generation, and a JSON report store. It is broader than `ResearchPort`, writes files, and presents its own assistant/report experience. It must not be exposed as-is.
- Standard references are assembled from visited URLs; deep-mode finding citations can be accepted from model-generated `sourceUrl` values. The system exposes raw source records, which is valuable, but hallucinated or mis-bound citations are not structurally prevented end to end. Tori must rebind citations to normalized retrieved evidence and reject unknown URLs.
- WebSocket logs are useful but not a stable, versioned lifecycle contract. The deep callback is richer but currently in-process. Branch counts, source-read counts, and conflict/verification phases require normalization and truthful definitions.
- Disconnect cancellation cancels the asyncio task, but there is no verified run-ID cancellation endpoint, durable cancellation acknowledgement, or proof that all nested HTTP/model tasks and browser resources promptly stop. `asyncio.gather` cancellation behavior is promising, not acceptance evidence.
- The bundled report store stores completed UI report data; it is not a checkpointed research state machine. No durable branch checkpoint/resume contract was found. A killed run should be treated as cancelled/failed with optional partial evidence, not silently resumed.
- Local-document mode points at a configured folder and can build/use worker memory/vector stores. Tori must instead pass a bounded run-specific staging view or document objects; the worker must never receive Tori's canonical Knowledge root.
- Browser/scraper options, file generation, MCP subprocesses, and document paths expand authority. The V1 worker profile should allow only approved HTTP retrieval or a Tori retrieval bridge, with image generation, uploads, arbitrary MCP, browser automation, and report-file generation disabled.

#### Assessment

GPT Researcher wins on adaptable mechanics and integration breadth, not on pristine boundaries. Its shortcomings are wrap-able without rewriting its research engine, but only if the POC proves that package mode can be reduced to a deterministic, bounded worker profile.

### 7.2 LangChain Open Deep Research

#### Verified strengths

- The current graph separates summarization, research, compression, and final-report models. It runs parallel research units, supervisor reflection, researcher tool loops, compression, and final synthesis. [Configuration](https://github.com/langchain-ai/open_deep_research/blob/main/src/open_deep_research/configuration.py), [graph](https://github.com/langchain-ai/open_deep_research/blob/main/src/open_deep_research/deep_researcher.py)
- Model construction uses LangChain's universal `init_chat_model`; models are configured separately by role. This is provider-neutral at the workflow level.
- The research and supervisor paths depend on reliable structured output and tool calling. The README states this explicitly. Local transport is feasible, but many local models will not meet the behavioral requirement.
- Search supports Tavily, native OpenAI/Anthropic search, `none`, and MCP tools. MCP makes a Tori retrieval bridge possible; however, SearXNG and DuckDuckGo are not first-class current `SearchAPI` selections in the inspected implementation.
- It has direct benchmark evidence: the repository includes Deep Research Bench result artifacts and reports RACE results for several model configurations. Those results used strong hosted models and do not predict LM Studio-local performance. [README evaluation](https://github.com/langchain-ai/open_deep_research#-evaluation)
- A LangGraph server provides a documented local HTTP API/Studio path. LangGraph can stream graph updates, cancel runs, and persist/checkpoint threads when configured. These are framework/runtime capabilities, not a complete Tori-specific run contract.

#### Material concerns

- **Verified current fact:** GitHub's repository page says, “This repository was archived by the owner on Aug 21, 2026. It is now read-only.” GitHub API metadata also reports `archived: true`. [Repository](https://github.com/langchain-ai/open_deep_research)
- There was no GitHub release, the last repository push was 2026-08-10, and 73 issues remained open at audit time. The MIT license permits a fork, but Tori should not casually become the maintainer of a large agent framework integration.
- The dependency list is broad: LangGraph server/CLI, multiple LangChain provider packages, Tavily, Exa, Linkup, Supabase, Azure, Google, AWS, MCP, Pandas, and LangSmith. Many are unused in a minimal configuration but remain dependency and vulnerability surface.
- Direct LM Studio use is not a documented first-class profile. A base URL can likely be supplied through the LangChain OpenAI model adapter or environment, but configuration plumbing and tool/structured-output behavior require proof.
- Adopting the LangGraph server directly would expose framework concepts—assistants, threads, runs, graph state, and streaming modes. Tori must translate them at the adapter; Conversation, Projects, Knowledge, and UI must not learn LangGraph types.
- Checkpointing is only valuable if the chosen server/checkpointer persists the right state safely. The graph compiles subgraphs without an embedded checkpointer; restart/resume is therefore a deployment/runtime design, not a guaranteed repository feature.
- Citations are primarily carried in research notes and prompts. Raw tool outputs are available, but the inspected code does not provide a Tori-grade claim-to-evidence ledger or structural citation verifier.

#### Assessment

Technically, this is the strongest challenger. Operationally, archival changes the verdict. Use it to shape `ResearchPort` events and a POC comparison, or adopt a credible maintained successor/fork. Do not pin Tori V1 to this read-only repository merely because the graph is elegant.

### 7.3 Stanford STORM / Co-STORM

#### Verified strengths

- STORM is explicitly a knowledge-curation and Wikipedia-like article-generation system. It uses perspective-guided question asking, simulated grounded conversations, outline generation, cited article generation, and polishing. Co-STORM adds human participation, multi-agent discourse, and a dynamic mind map. [README](https://github.com/stanford-oval/storm)
- `STORMWikiRunner` and `CoStormRunner` are real Python APIs; different model roles can use different models.
- Current package documentation uses LiteLLM for model and embedding access. Retrieval options include SearXNG, DuckDuckGo, Brave, Tavily, Bing, Serper, Google, Azure AI Search, and a vector retriever for user documents.
- It emits useful stage artifacts such as raw search results, conversation logs, URL-to-information mappings, outlines, and cited articles. Those artifacts aid inspection and stage replay.
- License: MIT. Latest release found: `v1.1.0`, published 2025-01-23.

#### Material concerns

- STORM's product shape is article/knowledge curation, not a general user-request research worker. Co-STORM's collaborative agents and discourse can easily become a second visible assistant experience if surfaced directly.
- The public examples emphasize OpenAI and Ollama. LiteLLM makes an OpenAI-compatible LM Studio route plausible, but no first-class LM Studio recipe was found. DSPy prompt signatures and output formatting need local-model proof.
- Progress is primarily console/log/stage oriented. No stable local HTTP/MCP protocol, typed progress stream, or first-class cancellation contract was found.
- Stage files allow rerunning later stages, but there is no general run checkpoint/resume/cancellation protocol. Output directories are worker-owned persistence and must not become canonical Tori Knowledge.
- Dependencies include DSPy, LiteLLM, Qdrant client, sentence-transformers, Torch, Pandas, document parsers, search clients, and UI-related packages. Native venv operation is possible but heavy.
- Repository push activity stopped at 2025-09-30 in GitHub metadata inspected on 2026-08-29. The project is not archived, but the activity signal is weaker than GPT Researcher or smolagents.

#### Assessment

Do not force STORM into Deep Research V1. It is a better future candidate for user-steered knowledge exploration, article curation, or a Second Brain staging workspace—still behind Tori authority and promotion workflows. Its source/reference mapping is worth learning from.

### 7.4 Hugging Face Open Deep Research / smolagents

#### Verified strengths

- The example builds a manager plus web-research agent with planning intervals, iterative tool use, direct page navigation, archive search, local file inspection, and visual question answering. The upstream claim is 55% pass@1 on GAIA validation. [Example README](https://github.com/huggingface/smolagents/tree/main/examples/open_deep_research)
- The maintained smolagents library supports OpenAI-compatible `api_base`, LiteLLM, local Transformers models, tool-calling agents, MCP tools, streaming outputs, and multiple remote execution backends.
- The library is active: GitHub reported activity through 2026-08-25; latest release found was `v1.26.0`, published 2026-05-29. License: Apache-2.0.

#### Material concerns

- This is an example/reference implementation, not a stable Deep Research service or package contract. Its executable entry point and Gradio UI are thin wrappers around an agent object.
- The example uses Serper/SerpAPI-style keyed Google search rather than SearXNG or no-key DuckDuckGo, creates a `downloads_folder`, logs into Hugging Face, and has a very large task-specific dependency list including Torch/Transformers, scientific packages, media tooling, document parsers, and dataset tooling.
- Most importantly, the manager is a `CodeAgent` with `additional_authorized_imports=["*"]`. Upstream explicitly warns that `LocalPythonExecutor` is **not a security sandbox**. This is a disqualifying default for a Tori information-gathering worker.
- Replacing the manager with a strictly allowlisted `ToolCallingAgent` could improve authority fit, but that would become a Tori-designed research workflow rather than adoption of a durable external subsystem.
- No durable run store, checkpoint/restart contract, stable citation ledger, or first-class cancellation protocol was found in the example.

#### Assessment

Use smolagents as a reference for small agent/tool abstractions or a later experiment, not as Tori's Deep Research V1 worker. Do not run the shipped code-agent configuration with access to Tori or user files.

### 7.5 Jina AI node-DeepResearch

#### Verified strengths

- The project implements an iterative search/read/reason/reflection loop with token budgets and answer evaluation. It explicitly targets concise deep answers rather than long reports. [README](https://github.com/jina-ai/node-DeepResearch)
- It exposes a local OpenAI-compatible `/v1/chat/completions` API with streaming and URL citation annotations.
- It explicitly documents LM Studio through `LLM_PROVIDER=openai`, `OPENAI_BASE_URL=http://127.0.0.1:1234/v1`, a placeholder API key, and a selected local model. It warns that the model must reliably produce structured output.
- It supports OpenAI, Gemini, and Vertex model clients, is Apache-2.0, and had repository activity through 2026-05-01. Latest release found was `v1.4.0` from 2025-02-12.
- The Node dependency surface is smaller than the Python candidates, though still substantial.

#### Material concerns

- The inspected configuration throws if `JINA_API_KEY` is absent. Search/read and related quality mechanisms are coupled to Jina services, with optional Brave/Serper paths also present. This fails Tori's no-mandatory-hosted-search preference.
- It is intentionally not a long-form report engine. It lacks explicit parallel research branches, local-document research, academic retrievers, and a Tori-suitable artifact model.
- Streaming exposes generated thinking/search/read text, but no stable run lifecycle, cancellation acknowledgement, source-count contract, checkpointing, or resume protocol was found.
- The OpenAI-compatible response is convenient for final answers but too narrow for Tori's required raw evidence, partial results, branch state, and truthful lifecycle record unless extended.
- Citation annotations contain URL/title/quote metadata, but end-to-end evidence binding still requires verification.

#### Assessment

This is a useful proof that LM Studio transport and a narrow local HTTP worker can coexist. It is not the primary worker because its retrieval is vendor-coupled and its output goal is narrower than Tori Deep Research V1.

## 8. Provider neutrality and LM Studio proof of fit

### Required invariant

```text
research workflow semantics
          independent of
Ollama / LM Studio / llama.cpp / future provider
```

Tori's `ResearchRequest` should refer to Tori-owned model profile roles or portable capability requirements, never an Ollama or LM Studio model object. The worker adapter translates those roles to its native configuration. A later adapter can instead proxy calls through Tori's existing provider abstraction if that becomes practical.

### Leading GPT Researcher path

Conceptually, without configuring the user's actual instance:

```text
GPT Researcher model role
        |
        v
langchain_openai.ChatOpenAI / OpenAIEmbeddings
        |
        v
OPENAI_BASE_URL=http://127.0.0.1:1234/v1
        |
        v
LM Studio selected chat and embedding model(s)
```

The POC configuration should use the `openai:` provider for fast, smart, and strategic roles and point the OpenAI client base URL at LM Studio. It must not select the `ollama:` provider. The adapter should pass an arbitrary non-secret API key only if the OpenAI client requires a value and the local endpoint is unauthenticated.

LM Studio officially documents `/v1/chat/completions`, `/v1/responses`, `/v1/embeddings`, and changing an OpenAI client's base URL to `http://localhost:1234/v1`. [LM Studio OpenAI compatibility](https://lmstudio.ai/docs/developer/openai-compat)

**Transport compatibility is not model capability.** GPT Researcher deep mode asks models for JSON-shaped query plans, follow-up questions, findings, and citations; it applies JSON repair and text fallbacks, which may make it more tolerant than strict tool-calling graphs. A viable local model still needs:

- reliable instruction following and JSON/schema-shaped output;
- sufficient context for accumulated evidence;
- adequate synthesis quality and citation discipline;
- concurrency and latency acceptable at configured breadth/depth;
- no incompatible reasoning/token/temperature semantics; and
- a compatible embedding model or a verified way to avoid/replace embedding-dependent paths.

LM Studio supports an embeddings endpoint, but a chat model is not automatically an embedding model. The POC must prove whether GPT Researcher can target a separately loaded embedding model through the same endpoint, use an approved alternate embedding provider, or bypass embeddings for the selected Deep Research path. No Ollama dependency should be introduced to solve this.

LangChain Open Deep Research has the harder local-model bar: its current graph directly binds tools and invokes structured-output schemas in several roles. “Can connect” is therefore substantially weaker than “can complete the graph correctly.”

## 9. Search-backend direction

**Do not make Tavily, Exa, Jina, or another paid cloud search API mandatory.**

Recommended direction:

1. **POC:** compare GPT Researcher's native DuckDuckGo and Searx/SearXNG adapters. DuckDuckGo minimizes setup; SearXNG offers a better long-term self-hosted/provider-neutral boundary. Record failure rates, result quality, throttling, and raw provenance.
2. **V1 architecture:** define a research-run retrieval boundary owned by Tori. The worker may call a narrow local retrieval bridge or a candidate-specific custom retriever adapter. It receives only the approved query/budgets and returns normalized candidates/evidence.
3. **Reuse, not bypass:** reuse Tori's existing search and source-retrieval policy concepts, provenance validation, endpoint rules, and untrusted-content handling. Do not make the current single-search `SearchPort` pretend to be the research engine.
4. **Future:** a local SearXNG profile is preferred when approved and available; DuckDuckGo remains a possible no-key adapter. Academic requests may add arXiv/OpenAlex/Semantic Scholar adapters. Direct URLs and bounded user-supplied sources should bypass general web search where appropriate.

One Deep Research request should authorize a bounded research plan, not prompt the user for consent on every generated subquery. The future contract must therefore define request-level disclosure and budgets, query auditability, mid-run cancellation, and no silent provider fallback. Search-provider selection remains explicit Tori configuration.

## 10. Integration-surface comparison

### Option A — separate native project with narrow local HTTP + SSE/WebSocket

**Recommended V1 shape if the POC passes.** Place the worker and its pinned venv outside Tori under a separately approved `<project-parent>` path. Expose only loopback, versioned endpoints such as create run, stream normalized events, get result, and cancel run. The wrapper imports GPT Researcher; it does not expose GPT Researcher's bundled FastAPI application.

Advantages: clean process/dependency boundary, natural concurrent-run supervision, streaming, prompt cancellation, health/version reporting, and easy worker replacement. Risks: Tori must authenticate/authorize loopback requests appropriately, supervise service lifecycle, prevent broad endpoints, and define durable ownership clearly.

### Option B — separate native project/package invoked as one isolated process per run

**Recommended POC shape and acceptable V1 fallback.** Tori sends a bounded request over stdin or a run-specific file descriptor; the worker emits versioned NDJSON events/result over stdout. Cancellation terminates the process group after a grace period.

Advantages: strongest configuration isolation, simple cleanup, no always-on server, easy runtime network/file restrictions, and robust kill semantics. Risks: warm-up cost, more work for concurrency, and no inherent resume across process loss. This is preferable to importing third-party packages into Tori's process.

### Option C — MCP/stdio worker

**Not primary.** GPT Researcher's dedicated MCP server is intended to present research as a tool to assistants. MCP may be useful as a transport, but its generic tool result/progress/cancellation semantics must be checked against `ResearchPort`; Tori still needs its own lifecycle and evidence contract. Do not make the worker an assistant or let it request unrelated tools.

### Option D — vendor/package directly inside Tori

**Reject for V1.** Candidate dependencies, release cadence, runtime globals, and security surfaces are too large. Vendoring would make upgrades and replacement harder and risks leaking LangChain/LangGraph/smolagents types into Tori core.

## 11. Research quality and citation comparison

- **GPT Researcher:** strongest balance of recursive mechanics and source access. It collects visited URLs and rich source records and can produce long reports. Citations remain model/prompt/post-processing dependent; Tori must verify every cited URL against the run's retrieved evidence and preserve raw source metadata.
- **Open Deep Research:** strongest demonstrated orchestration and benchmark evidence. Supervisor/researcher loops and compression are substantial. Benchmark results used hosted frontier models and do not establish local-model quality. A claim-to-evidence ledger is still absent.
- **STORM:** strongest explicit cited-article/reference design and perspective discovery. Its output objective is narrower and editorial; papers and user feedback acknowledge that generated articles need editing.
- **HF example:** strong task-solving mechanics but weak durable citation structure. GAIA pass@1 is a broad agent benchmark, not evidence of report citation fidelity.
- **Jina:** useful URL/title/exact-quote annotations and answer evaluation, but concise-answer optimization and vendor retrieval do not meet the complete V1 goal.

For every candidate, Tori should preserve three distinct levels:

1. retrieved source record and content metadata;
2. worker finding/claim with explicit source IDs and optional supporting excerpts; and
3. worker report plus Tori's accepted final presentation.

A final markdown footnote is not sufficient evidence binding. Unknown URLs, citations with no retrieved record, and claims with no support must be surfaced as validation warnings or rejected according to the future contract.

## 12. Progress, cancellation, durability, and partial results

The Tori contract should accept only objective, typed events. Suggested event families—not exact UI text—are:

- `run.accepted`, `plan.started`, `plan.completed`;
- `query.started`, `query.completed`, `source.discovered`, `source.retrieved`, `source.failed`;
- `branch.started`, `branch.completed`, `reflection.started`, `conflict.detected`;
- `synthesis.started`, `artifact.available`;
- `cancellation.requested`, `cancellation.acknowledged`; and
- one terminal `completed`, `cancelled`, or `failed` event.

Event payloads must contain verified counts and identifiers. Generated prose such as “comparing conflicting sources” is allowed only when the worker actually exposes such a phase; otherwise Tori should use honest generic status.

GPT Researcher can supply callback/log/WebSocket inputs for an adapter, but cancellation and nested resource cleanup need proof. Open Deep Research/LangGraph offers the best lifecycle substrate but would couple the adapter to LangGraph. STORM's files and smolagents/Jina streaming are not adequate contracts by themselves.

Tori should durably record request admission and terminal outcome when persistence is eventually approved. The worker may remain transient. For V1, restart may safely mark an in-flight transient run interrupted and preserve validated partial evidence; transparent resume should not be promised until a checkpoint contract is proven. Worker report stores, vector indexes, logs, and output directories are derived/noncanonical and replaceable.

## 13. Security and authority profile

The V1 worker profile should fail closed and permit only:

- configured model endpoint access;
- configured search/retrieval endpoints;
- bounded HTTP(S) retrieval through an approved adapter;
- a run-specific temporary working directory;
- bounded CPU, memory, concurrency, time, output, and source counts; and
- versioned stdout/stdio or loopback protocol messages.

Disable or exclude:

- arbitrary shell/Python/code execution;
- `additional_authorized_imports=["*"]` or equivalent;
- browser automation unless separately approved and sandboxed;
- arbitrary MCP server launch/configuration;
- filesystem paths supplied by the model;
- Tori runtime, repository, home, secrets, and unrelated project access;
- file upload/delete/report-export routes;
- image generation and downloads not required for research;
- runtime dependency installation; and
- silent network fallback or telemetry/tracing services.

Retrieved pages, MCP results, local documents, and worker outputs are untrusted data. They grant no authority and cannot modify Tori policy, Projects, tasks, memory, Knowledge, or configuration.

## 14. Knowledge / Second Brain boundary

- Research run artifacts and findings are not automatically curated memory.
- A research report is not automatically permanent Knowledge.
- Worker memory, vector stores, report stores, checkpoints, output folders, and mind maps are not canonical Tori memory or Knowledge.
- Tori may provide bounded, user-approved source material to a run without transferring ownership of the Knowledge registry.
- Future promotion of a report, finding, or source into Knowledge/Second Brain requires a Tori-owned, user-approved workflow with provenance and review.
- Deleting/replacing a worker must not delete or reinterpret Tori's accepted research records or curated Knowledge.

## 15. Exact standalone POC questions and gates

The POC should occur outside Tori and answer these questions with recorded versions, configuration, timings, events, and artifacts.

### Model and LM Studio

1. Can GPT Researcher complete standard and deep modes through `OPENAI_BASE_URL=http://127.0.0.1:1234/v1` using the `openai:` provider with no Ollama process or Ollama-specific client?
2. Which tested local model reliably produces query plans, follow-ups, findings, and final synthesis at breadth 2–3/depth 2? What failures occur with malformed JSON, context limits, and concurrency?
3. Can fast/smart/strategic roles use one model and, separately, distinct models without changing workflow code?
4. What embedding calls occur in each path? Can LM Studio serve the required embedding model concurrently or can embedding-dependent behavior be disabled/replaced without quality loss?
5. Which OpenAI-compatible parameters does LM Studio reject or ignore, including tool/schema, streaming usage, reasoning effort, temperature, token limits, and parallel requests?

### Retrieval and evidence

6. Do native DuckDuckGo and SearXNG paths work without paid keys, and what are their rate-limit/failure characteristics on identical tasks?
7. Can a custom retriever bridge return Tori-normalized URL/content records without changing GPT Researcher's research workflow?
8. Are every final citation and every deep finding URL members of the actually retrieved source set? Can deliberate prompt injection or a model-invented URL escape validation?
9. Can the adapter export queries, visited URLs, source title/final URL/retrieval time/content hash or bounded excerpt, failed retrievals, finding-to-source links, and report without exposing secrets or full sensitive documents?
10. What does “source reviewed” mean operationally, and can a verified count distinguish search snippets, successfully retrieved pages, duplicate URLs, and failed pages?

### Lifecycle and control

11. Can callbacks/logs be mapped deterministically to the proposed event families without parsing unstable human prose?
12. Does cancellation during planning, search, page retrieval, nested deep branches, model streaming, and final synthesis stop promptly? Are child tasks, sockets, browser/scraper resources, and temporary files closed?
13. Does a cancelled run emit exactly one terminal state and preserve only explicitly allowed partial evidence?
14. What happens on worker crash, Tori restart, LM Studio restart, search timeout, malformed worker output, and loss of the streaming connection?
15. Can one run's configuration, sources, callbacks, and cancellation never affect a concurrent run? If not, use one process per run.

### Isolation and operations

16. What is the minimal pinned dependency set for package-only deep research? Can FastAPI UI, output converters, image generation, Ollama packages, SQLAlchemy, arbitrary MCP, and unused providers be excluded?
17. Does any code attempt runtime `pip install`, write outside the run directory, read environment secrets beyond its allowlist, create persistent logs/indexes, or contact tracing/telemetry services?
18. Can the worker run native Linux in a per-project venv with network egress limited to the approved LM and retrieval endpoints and no access to Tori runtime?
19. Is the upstream package/API stable enough to pin, and what adapter contract tests detect breaking upgrades?
20. Does a minimal Option B runner prove the semantics cleanly? If yes, what concrete concurrency/restart need justifies moving to Option A for V1?

### Acceptance gates

Proceed to a Deep Research V1 contract only if the POC establishes:

- no Ollama dependency in the chosen runtime path;
- successful LM Studio transport with at least one explicitly named capable local model, while documenting that other models are unsupported until tested;
- a no-mandatory-paid-search configuration;
- raw source/evidence export sufficient for Tori-side citation validation;
- deterministic typed progress adequate for truthful presentation;
- prompt cancellation with bounded cleanup;
- no runtime dependency installation or unauthorized file/network access;
- isolation from Tori runtime and canonical Knowledge;
- acceptable dependency/latency/resource cost; and
- a replaceable adapter contract containing no GPT Researcher, LangChain, LangGraph, LM Studio, Ollama, or SearXNG types.

If citation binding, cancellation cleanup, or isolation fails, the verdict becomes **do not select GPT Researcher for V1** until repaired upstream or in the isolated adapter. If only durable resume fails, V1 may explicitly support nonresumable runs with truthful interruption and partial-result semantics.

## 16. Recommended decision

1. Approve a **standalone, disposable Option B technology POC** for GPT Researcher, outside Tori, with LM Studio plus DuckDuckGo/SearXNG and no Ollama.
2. Use LangChain Open Deep Research as a comparison fixture for event/lifecycle and quality design only; investigate whether the archive points to a maintained successor before considering adoption.
3. If the POC passes, draft the Tori-owned `ResearchService` / `ResearchPort` contract before any production dependency or worker installation.
4. Prefer **Option A, a narrow loopback HTTP + SSE/WebSocket service**, for V1 only when the POC demonstrates a real need beyond one-process-per-run isolation. Keep Option B as the simpler fallback.
5. Do not vendor a candidate into Tori, adopt its UI/assistant identity, or treat worker storage as canonical truth.

## 17. Evidence links

### Tori authority

- `docs/00_MISSION.md` through `docs/06_ARCHITECTURE.md`
- `docs/ARCHITECTURE_GOVERNANCE.md`
- `docs/design/SEARCH_PROVIDER_CONTRACT.md`
- `docs/design/KNOWLEDGE_PROVIDER_CONTRACT.md`
- `src/tori/providers/openai_compatible.py`
- `src/tori/search_port.py`
- `src/tori/source_retrieval.py`

### Upstream

- [GPT Researcher repository](https://github.com/assafelovic/gpt-researcher), [configuration](https://docs.gptr.dev/docs/gpt-researcher/gptr/config), [search engines](https://docs.gptr.dev/docs/gpt-researcher/search-engines/search-engines), [package API](https://docs.gptr.dev/docs/gpt-researcher/gptr/pip-package), [deep research](https://docs.gptr.dev/docs/gpt-researcher/gptr/deep_research), [local documents](https://docs.gptr.dev/docs/gpt-researcher/context/local-docs)
- [LangChain Open Deep Research repository and archive notice](https://github.com/langchain-ai/open_deep_research), [configuration source](https://github.com/langchain-ai/open_deep_research/blob/main/src/open_deep_research/configuration.py), [graph source](https://github.com/langchain-ai/open_deep_research/blob/main/src/open_deep_research/deep_researcher.py)
- [STORM / Co-STORM repository](https://github.com/stanford-oval/storm), [STORM paper](https://arxiv.org/abs/2402.14207), [Co-STORM paper](https://arxiv.org/abs/2408.15232)
- [Hugging Face Open Deep Research example](https://github.com/huggingface/smolagents/tree/main/examples/open_deep_research), [smolagents repository](https://github.com/huggingface/smolagents)
- [Jina node-DeepResearch repository](https://github.com/jina-ai/node-DeepResearch)
- [LM Studio OpenAI-compatible endpoint documentation](https://lmstudio.ai/docs/developer/openai-compat), [structured output documentation](https://lmstudio.ai/docs/developer/openai-compat/structured-output), [tool-use documentation](https://lmstudio.ai/docs/developer/openai-compat/tools)

## 18. Explicit unknowns after audit

No candidate was executed. Therefore local-model research quality, LM Studio concurrency, exact embedding behavior, cancellation cleanup, event stability, minimal install size, source-citation fidelity under adversarial input, and resource consumption remain POC unknowns. The audit does not claim these checks passed.
