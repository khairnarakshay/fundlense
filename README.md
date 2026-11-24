# FundLense AI – AI-Powered Mutual Fund Portfolio Intelligence

FundLense AI is the artificial intelligence layer of FundLense, designed to transform mutual fund portfolio data into understandable, contextual and knowledge-grounded insights.

Instead of relying on an LLM to calculate financial metrics, FundLense follows a **deterministic analysis + Generative AI** approach:

- Python computes portfolio metrics using verified financial data.
- LLMs explain the computed results in natural language.
- Retrieval-Augmented Generation (RAG) provides a foundation for answering questions using curated financial knowledge.
- PostgreSQL with pgvector stores and retrieves document embeddings.
- User-level data isolation protects private portfolio and knowledge-base information.

The goal is to make investment data easier to understand through AI while keeping financial calculations traceable and separate from LLM-generated explanations.

**Repository:** [FundLense](https://github.com/khairnarakshay/fundlense)

---

## 1. The Problem

Investors often have mutual fund statements containing holdings, transactions, invested amounts, NAV information and other financial details.

Understanding this information manually can be difficult. Investors may need to:

- Review multiple mutual fund holdings.
- Understand asset allocation and AMC exposure.
- Identify portfolio concentration.
- Compare invested amounts with current portfolio value.
- Understand financial terminology and portfolio metrics.
- Find relevant information from financial documents.

Traditional dashboards can display numbers, but they do not always explain what those numbers mean.

**FundLense AI aims to bridge this gap by combining structured financial analysis with Generative AI and document retrieval.**

## 2. AI Architecture

The AI layer is organized into separate components for portfolio analysis, LLM integration, RAG, embeddings, memory and prompt management.

```text
                 FUNDLENSE AI
                       |
          +------------+------------+
          |                         |
   Portfolio Intelligence      Knowledge Base
          |                         |
   Portfolio Snapshot          Documents
          |                         |
   Deterministic Analysis       Text Extraction
          |                         |
   Verified Metrics             Chunking
          |                         |
          |                      Embeddings
          |                         |
          |                    PostgreSQL
          |                     + pgvector
          |                         |
          +------------+------------+
                       |
                AI Context Layer
                       |
                LangChain LLM
                       |
             Natural Language Output
                       |
             Portfolio Insights / Chat
```

*Conceptual architecture of the AI layer. The RAG subsystem and portfolio-aware LLM services are separate components in the current codebase; they are not yet connected into one unified RAG chat pipeline.*

## 3. Core AI Capabilities

### 3.1 Deterministic Portfolio Analysis

FundLense does not ask an LLM to calculate financial numbers.

The portfolio analysis engine uses Python to process a structured portfolio snapshot and calculate metrics independently of any LLM provider.

Current analysis includes:

- Total portfolio value.
- Total invested amount.
- Overall gain or loss and gain percentage.
- Holding-level market value and portfolio weight.
- Asset-type allocation.
- AMC allocation.
- Largest holding and AMC exposure.
- Portfolio concentration using the Herfindahl-Hirschman Index (HHI).
- Weighted expense ratio.
- Data completeness warnings, including unresolved schemes and stale NAV information.

Some metrics, such as XIRR, SIP classification and portfolio overlap, are explicitly reported as not computed where the required data assumptions are not yet confirmed.

**Key design principle:** Financial calculations remain in deterministic Python code. The LLM is not responsible for generating or modifying those numbers.

### 3.2 LLM-Powered Portfolio Insights

FundLense uses LangChain to integrate with configurable Large Language Model providers.

Supported providers in the current implementation:

- Hugging Face
- Groq
- Google Gemini

The provider factory creates a LangChain chat model from validated configuration. The application uses LangChain's standard interfaces, allowing the provider to be changed without rewriting the downstream application services.

AI-powered functionality includes:

- Natural-language portfolio explanations.
- Portfolio-related question answering.
- Structured portfolio report generation.
- Plain-language explanations of allocation and concentration.
- Data-quality observations and points for the investor to review.

The model receives a verified portfolio analysis as context and is instructed not to invent missing values or perform new financial calculations.

### 3.3 Retrieval-Augmented Generation (RAG)

FundLense contains a modular RAG subsystem for retrieving relevant information from an approved knowledge base.

The RAG pipeline follows these stages:

1. **Document ingestion:** Accepts document content through the ingestion service.
2. **Text normalization:** Cleans extracted text and normalizes line endings and whitespace.
3. **Chunking:** Splits documents into smaller, overlapping text chunks.
4. **Embedding generation:** Converts chunks into numerical vector representations.
5. **Vector storage:** Stores document chunks and embeddings in PostgreSQL using pgvector.
6. **Semantic retrieval:** Converts a user question into an embedding and retrieves relevant chunks using cosine distance.
7. **Context preparation:** Returns relevant, typed retrieval results for downstream AI services.

Supported document formats in the extraction module:

- PDF
- Markdown
- TXT

The ingestion service also supports document checksums, unchanged-document detection, re-indexing and atomic replacement of document chunks.

**Important:** The RAG ingestion and retrieval services are implemented as a separate subsystem. The current portfolio chat service does not yet invoke this retrieval pipeline, so it should not be described as a fully integrated RAG-powered portfolio chatbot.

### 3.4 Embedding Providers

The embedding factory supports multiple embedding backends:

| Provider | Purpose |
|---|---|
| FastEmbed | Local ONNX-based embedding generation |
| Google Gemini | Hosted embedding generation |
| Fake embeddings | Deterministic feature hashing for tests and plumbing checks |

The default FastEmbed model configured in the code is `BAAI/bge-small-en-v1.5`, which produces 384-dimensional embeddings.

The implementation validates embedding dimensions before storage and associates each vector with its embedding model identifier.

Fake embeddings are not semantic embeddings and should not be used for production knowledge retrieval.

### 3.5 PostgreSQL + pgvector

FundLense uses PostgreSQL with the pgvector extension for persistent vector storage.

The RAG data model includes:

- `KnowledgeDocument` – document metadata and normalized source content.
- `KnowledgeChunk` – chunk content, embedding and associated metadata.

Vector retrieval uses cosine distance and an HNSW index.

The vector store also enforces visibility rules:

- Shared knowledge documents can be retrieved by users.
- Private knowledge documents are restricted to their owner.
- Queries only compare vectors generated by the currently configured embedding model.

### 3.6 AI Conversation Memory

The repository includes a persistent memory design with three complementary techniques:

**Sliding Window**
- Keeps recent messages within a configurable token budget.
- Estimates token usage to control prompt size.

**Rolling Conversation Summary**
- Compresses older conversation history into a summary.
- Keeps recent messages available verbatim.

**Long-Term User Memory**
- Extracts explicitly stated user goals, investment horizons and preferences.
- Validates extracted information before storage.
- Deduplicates memories and applies a per-user limit.

Conversation and memory models are present in the codebase, along with supporting storage and memory services. However, the current chat endpoint is still single-turn and does not yet wire these memory components into its request flow.

---

## 4. AI Safety and Reliability

Financial applications require more than good prompts. They need reliable calculations, clear boundaries and data isolation.

FundLense applies several safeguards:

### Grounded Responses
The LLM is instructed to use only verified portfolio information provided by the application.

### No AI-Based Financial Calculations
Financial metrics are calculated by Python services, not generated by the model.

### No Personalized Buy/Sell Advice
The AI layer is instructed not to recommend buying, selling, switching or redeeming specific mutual funds.

### Facts vs. Interpretation
The model is instructed to distinguish verified financial facts from its own explanations.

### User-Level Data Isolation
AI endpoints require authentication. Portfolio information is fetched for the authenticated user, and private RAG chunks are filtered at the database query level.

### RAG Input Screening
The ingestion and retrieval modules include prompt-injection screening for suspicious document chunks.

### Data Completeness Warnings
Unresolved schemes and stale NAV data are surfaced rather than silently treated as accurate values.

---

## 5. Technology Stack

| Category | Technologies |
|---|---|
| Backend | Python, Django, Django REST Framework |
| LLM Integration | LangChain |
| LLM Providers | Hugging Face, Groq, Google Gemini |
| RAG | Document ingestion, text chunking, semantic retrieval |
| Embeddings | FastEmbed, Google Gemini |
| Vector Database | PostgreSQL, pgvector |
| Vector Search | Cosine Distance, HNSW |
| Data Validation | Pydantic |
| Document Processing | PDF, Markdown, TXT extraction |
| API Security | Django authentication, DRF permissions |
| Configuration | Environment-based AI provider configuration |

## 6. AI Module Structure

```text
ai_intelligence/
│
├── application/
│   ├── chat_service.py
│   ├── portfolio_analysis_service.py
│   └── portfolio_report_service.py
│
├── domain/
│   ├── policies.py
│   ├── schemas.py
│   └── exceptions.py
│
├── embeddings/
│   └── factory.py
│
├── llm/
│   ├── configuration.py
│   └── factory.py
│
├── memory/
│   ├── context_window.py
│   ├── conversation_store.py
│   ├── long_term.py
│   └── summarizer.py
│
├── portfolio/
│   ├── analysis_engine.py
│   └── context_builder.py
│
├── prompts/
│   ├── system.py
│   └── portfolio_report.py
│
├── rag/
│   ├── chunking.py
│   ├── ingestion.py
│   ├── retrieval.py
│   └── vector_store.py
│
├── models.py
├── urls.py
└── views.py
```

## 7. AI API Endpoints

The AI module exposes authenticated REST API endpoints.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/ai/portfolio-analysis/` | POST | Returns deterministic portfolio analysis |
| `/api/ai/portfolio-report/` | POST | Returns portfolio metrics with an LLM-generated narrative |
| `/api/ai/chat/` | POST | Answers a question using the authenticated user's current portfolio analysis |

All three endpoints require authentication.

### Example: Portfolio Chat

**Request**

```http
POST /api/ai/chat/
Content-Type: application/json
```

```json
{
  "question": "Explain my current mutual fund portfolio allocation."
}
```

The application builds the authenticated user's portfolio snapshot, runs deterministic analysis, prepares a grounded prompt and invokes the configured LLM.

The response contains the AI-generated answer, analysis date, warnings and metrics that were not computed.

## 8. Configuration

The LLM provider is configured through Django settings populated from environment variables.

Example configuration:

```env
AI_LLM_PROVIDER=groq
AI_LLM_MODEL_ID=your-model-id
AI_LLM_API_TOKEN=your-api-token
AI_LLM_TEMPERATURE=0.1
AI_LLM_TIMEOUT_SECONDS=60
```

Supported `AI_LLM_PROVIDER` values:

- `huggingface`
- `groq`
- `gemini`

RAG embedding configuration is handled separately:

```env
AI_EMBEDDING_PROVIDER=fastembed
AI_EMBEDDING_MODEL_ID=BAAI/bge-small-en-v1.5
AI_EMBEDDING_DIMENSIONS=384
```

For Gemini embeddings, configure the corresponding embedding API token.

Do not commit `.env` files, API tokens, database passwords or Django secrets to source control.

## 9. Current Implementation Status

| Component | Status |
|---|---|
| Deterministic portfolio analysis | Implemented |
| LLM provider abstraction | Implemented |
| Portfolio-aware AI chat | Implemented |
| Structured AI portfolio report | Implemented |
| Per-user report caching | Implemented |
| RAG document extraction and chunking | Implemented |
| Embedding provider abstraction | Implemented |
| PostgreSQL + pgvector storage | Implemented |
| Semantic vector retrieval | Implemented |
| Prompt-injection screening in RAG | Implemented |
| Conversation persistence services | Present; not wired into current chat endpoint |
| Rolling conversation summary | Supporting module present |
| Long-term user memory | Supporting module present |
| RAG-grounded portfolio chat | Integration pending |

## 10. Project Vision

The long-term direction of FundLense AI is to build a context-aware financial intelligence assistant that can combine:

