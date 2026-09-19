[![Open Exchange](https://img.shields.io/badge/Available%20on-Intersystems%20Open%20Exchange-00b2a9.svg)](https://openexchange.intersystems.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat&logo=AdGuard)](LICENSE)
[![InterSystems IRIS](https://img.shields.io/badge/InterSystems-IRIS%202026%2B-blue.svg)](https://www.intersystems.com/)
[![Embedded Python](https://img.shields.io/badge/Embedded%20Python-pyprod-informational.svg)](https://github.com/intersystems/pyprod)

# 📥 dc.omniIngest

**The Document Ingestion Gateway for InterSystems IRIS**

> *Drop a file in a folder. Any format. Hybrid-search-ready rows.*

---

## 🌌 Motivation

With [`dc.omniEmbedding`](https://openexchange.intersystems.com/package/omniEmbedding) and [`dc.omniReRank`](https://openexchange.intersystems.com/package/omniReRank) shipped, IRIS had the middle and the end of the RAG chain. The beginning was still hand-written glue, every single time:

- **Parsing** is not "open and read" — a PDF needs a layout model, a DOCX is a zip of XML, a PPTX hides its tables in shape trees
- **Chunking** is where retrieval quality is won or lost, and the naive fix (`split(text, 1000)`) silently destroys it: it cuts tables in half, separates a heading from the content it introduces, and treats a character budget as if it were a token budget
- **Vectorizing** means getting `TO_VECTOR()` and the dimension right — and `%Vector` has no stable representation on the Embedded Python side, so the obvious approach fails
- **Hybrid search** requires a schema that was designed for it *up front*; retrofitting an iFind index and a vector column onto a table full of rows is a migration, not a feature

Worse, the failure mode of bad ingestion is **silent**. Nothing throws. Your RAG just answers slightly worse, forever.

**`dc.omniIngest` changes that.**

Point it at a folder. Every file that lands there is parsed, chunked with the document's own structure preserved, vectorized through whichever provider your `%Embedding.Config` names, and written to a SQL table where keyword search and vector search live on the same row.

- ✅ **Five formats, one folder:** PDF · DOCX · PPTX · Markdown · TXT
- ✅ **Structure-aware chunking:** tables stay whole, headings stay attached, provenance survives to the answer
- ✅ **Pure Python Production:** Business Service, Process and Operation via [`intersystems_pyprod`](https://github.com/intersystems/pyprod) — no ObjectScript on the main path
- ✅ **Hybrid-ready schema:** `%iFind.Index.Basic` over the raw text and a native `VECTOR` column on the same row, from day one
- ✅ **CPU only, network free:** Docling runs on a plain CPU, layout models are baked into the image — ingestion makes zero outbound calls except the embedding itself
- ✅ **Secure by default:** the Production screen exposes a **config name**, never an API key
- ✅ **Fully observable:** every file and every chunk is a persistent message — the whole journey is replayable in the Message Viewer and queryable in SQL
- ✅ **Provider-agnostic:** zero code coupling to `dc.omniEmbedding`; it dispatches to whatever `EmbeddingClass` the config names

---

## 🛠️ How It Works

`dc.omniIngest` sits between a watched folder and your chunk table, applying three architectural pillars:

1. **The document tree is the unit of work, not the character count.** Docling returns a `DoclingDocument` — a tree of headings, paragraphs, lists and tables. Chunking walks that tree. Throwing it away to slice a flat string would mean paying the parsing cost and discarding the result.
2. **Vectors are marshalled where they are born.** `%Vector` has no stable Embedded Python representation — a `SELECT` of a vector column from Python fails with *"Invalid argument type"*. A thin ObjectScript class converts to CSV at the source; Python only runs the `INSERT`.
3. **A chunk's failure is that chunk's failure.** Not the document's, not the folder's. Every chunk is written in its own transaction, and the log names the document and the index.

### **Core Components**

| Class | Role |
|---|---|
| `dc.omniIngest.FileWatcherService` | Business Service over `EnsLib.File.InboundAdapter` — extension filter, `doc_key` (original filename) and `doc_id` (SHA-256 of content) |
| `dc.omniIngest.ParseChunkProcess` | Docling parse (CPU, OCR off) → `HybridChunker` → heading contextualization → intra-section overlap |
| `dc.omniIngest.EmbeddingBridgeOperation` | Embedding call, dimension check, transactional `INSERT ... TO_VECTOR()`, reingestion replace |
| `dc.omniIngest.Embedder` | ObjectScript bridge — loads `%Embedding.Config`, dispatches to its `EmbeddingClass`, marshals `%Vector` → CSV |
| `dc.omniIngest.Schema` | Idempotent DDL — chunk table, iFind index, `doc_key` index, IRIS capability guard |
| `dc.omniIngest.Setup` | Post-load boot — create the table, promote target settings to `Ens.DataType.ConfigName` |
| `dc.omniIngest.OmniIngestProduction` | Production definition in code, not clicked into the UI |
| `IngestFileRequest` · `ChunkEmbedRequest` · `ChunkEmbedResponse` | Persistent messages, SQL-projected and indexed |

### **Architecture Overview**

```

┌─────────────────────────────────────────────────────────────┐
│                     Watched folder                          │
│              /data/omniingest/in/*.pdf|docx|pptx|md|txt     │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│       dc.omniIngest.FileWatcherService                      │
│  EnsLib.File.InboundAdapter (no WorkPath — see note)        │
│  extension filter · doc_key · doc_id (SHA-256)              │
└─────────────────────────┬───────────────────────────────────┘
                          │  IngestFileRequest
                          ▼
┌─────────────────────────────────────────────────────────────┐
│       dc.omniIngest.ParseChunkProcess                       │
│  DocumentConverter (CPU, do_ocr=False) → DoclingDocument    │
│  HybridChunker → contextualize() → intra-section overlap    │
└─────────────────────────┬───────────────────────────────────┘
                          │  ChunkEmbedRequest (one per chunk, in order)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│       dc.omniIngest.EmbeddingBridgeOperation                │
│  Embedder → %Embedding.Config → dc.omniEmbedding            │
│  dimension guard · TSTART · INSERT · reingest purge         │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              dc_omniIngest.DocumentChunk                    │
│  chunk_text (iFind) + chunk_vector (VECTOR) + provenance    │
│       one row — keyword and vector search together          │
└─────────────────────────────────────────────────────────────┘

```

### **Chunking Strategy**

This is the decision that determines retrieval quality, so it is spelled out.

**1. Structural chunking.** `HybridChunker` groups by tree element, respects table and section boundaries, merges undersized chunks and splits oversized ones by token count. A table that fits under the ceiling comes out whole, in a single chunk.

**2. Heading contextualization.** The text sent to the embedding carries the heading path in front of it. A chunk reading *"the limit is 30 days"* becomes, in vector space, *"Policies > Refunds > Deadlines — the limit is 30 days"*. The **raw** text, without the prefix, is what lands in `chunk_text` — that is what you display and what iFind indexes. Both travel together because they serve different purposes.

**3. Intra-section overlap.** `HybridChunker` does not do character overlap — it merges and splits. Since `chunk_overlap` is a dial operators need to turn, overlap is applied as a post-pass, copying the tail of the previous chunk into the head of the next one **only between chunks of the same section**. Overlapping across a section boundary would reintroduce exactly the context bleed that structural chunking exists to prevent.

The budget is reserved: the chunker receives `chunk_size - chunk_overlap` as its ceiling, and the overlap fills the rest. No chunk exceeds `chunk_size` after the inherited tail is glued on.

**Alternatives considered and rejected:**

| Alternative | Why not |
|---|---|
| **Fixed character windows** | Cuts tables in half, separates headings from content, confuses characters with tokens. Pays the Docling cost and discards the result. |
| **One chunk per page** | Cheap, perfect provenance. But page size has no relation to semantic unit — and Markdown and TXT have no pages. |
| **Semantic (sentence-similarity)** | Potentially better quality, but costs one embedding call per sentence *before* a chunk exists. Prohibitive in latency and cost. |

**Token counting.** `HybridChunker` requires a tokenizer, and the ready-made ones (HuggingFace, OpenAI) download model files on first use — which would break the no-network guarantee. `dc.omniIngest` implements `BaseTokenizer` with a character estimate that **divides by 3, not 4**. A typical BPE runs ~3.5–4 characters per token; dividing by 3 over-counts, so chunks land under the ceiling, never over. Erring toward small chunks is cheap; blowing the embedding model's window is a runtime error. Swapping in an exact tokenizer is a one-line change once you pre-download one.

---

## 📋 Prerequisites

- **InterSystems IRIS 2026.2+** with Interoperability enabled (`%Embedding.Config`, `%Library.Vector`, `%iFind.Index.Basic` are required)
- **Docker** and **Docker Compose** (the bundled dev container builds everything)
- **An embedding provider** reachable through [`dc-omni-embedding`](https://openexchange.intersystems.com/package/omniEmbedding) — installed automatically as an IPM dependency
- ~2.4 GB of image: CPU-only `torch`, `docling` 2.55.1 and the Docling layout models are baked in so ingestion never downloads at runtime

---

## 🛠️ Installation

### 1. **Clone the Repository**

```sh
git clone https://github.com/henryhamon/omniIngest.git
cd omniIngest
```

### 2. **Build and Run the Dev Container**

```sh
docker-compose up -d --build
```

The container comes up **ready**: ObjectScript classes loaded, Python hosts registered, the chunk table created and the Production defined. The first build is slow (torch and ~500 MB of Docling models), subsequent ones hit the layer cache.

### 3. **Or Install as an IPM Package**

```objectscript
zpm "install dc-omniIngest"
```

`dc-omni-embedding` is declared as a dependency and installs with it.

### 4. **Create an SSL configuration** (required for any SaaS embedding provider)

IRIS refuses outbound HTTPS without a named `Security.SSLConfigs` entry. Create one once, in `%SYS`:

```objectscript
zn "%SYS"
Do ##class(Security.SSLConfigs).Create("OmniHTTPS")
zn "IRISAPP"
```

### 5. **Register a credential**

`apiKey` is always a **credential name**, never the raw secret:

```objectscript
Set cred = ##class(Ens.Config.Credentials).%New()
Set cred.SystemName = "cohere-prod"
Set cred.Username = "apikey"
Set cred.Password = "co-...your-real-key..."
Do cred.%Save()
```

### 6. **Wire it into `%Embedding.Config`**

```objectscript
Set config = ##class(%Embedding.Config).%New()
Set config.Name = "omniingest-default"
Set config.EmbeddingClass = "dc.omniEmbedding.Interface"
Set config.VectorLength = 1024
Set config.Description = "Cohere embed-multilingual-v3.0"
Set config.Configuration = {
    "provider": "cohere",
    "modelName": "embed-multilingual-v3.0",
    "dimensions": 1024,
    "apiKey": "cohere-prod",
    "sslConfig": "OmniHTTPS"
}.%ToJSON()
Do config.%Save()
```

`Name` must match the item's `embedding config name` setting, and `VectorLength` must match the `chunk_vector` column's dimension — a mismatch is refused with **both** dimensions named, before anything is written.

> **No provider at hand?** `tests/dc/omniIngest/unittests/FakeEmbedding.cls` is a test double that derives a deterministic vector from the text, with no network and no credential. Point `EmbeddingClass` at it to exercise the whole pipeline. It is not semantic search — it is a wiring check.

### 7. **Use It**

Start the `dc.omniIngest.OmniIngestProduction` Production from **Interoperability > Configure > Production**, then drop a file:

```sh
docker cp handbook.pdf omniingest-iris-1:/data/omniingest/in/
```

Within one poll interval it is parsed, chunked, vectorized and stored. Processed files move to `/data/omniingest/archive`.

---

## 💡 Configuration Reference

Every setting is editable at runtime in **Interoperability > Configure > Production**, under the `omniIngest` category. Nothing is hardcoded.

### **FileWatcherService** (Business Service)

| Setting | Target | Default | Effect |
|---|---|---|---|
| `AcceptedExtensions` | Host | `pdf,docx,pptx,md,txt` | Comma-separated. Case-insensitive, leading dot optional. Anything else is refused without parsing, with a warning in the log. |
| `TargetConfigName` | Host | `ParseChunkProcess` | Item that receives the file for parsing. |
| `FilePath` | Adapter | `/data/omniingest/in` | Watched folder. |
| `ArchivePath` | Adapter | `/data/omniingest/archive` | Where files go after processing. |
| `FileSpec` | Adapter | `*` | File mask. |
| `CallInterval` | Adapter | `5` | Seconds between polls. |

> **`WorkPath` is deliberately left empty.** With it set, the adapter renames the file — `Annual Report 2025.pdf` becomes `Annual_Report_2025.pdf_2026-09-17_19.48.11.114`. Spaces become underscores and a timestamp is appended. The loss is irreversible, and the original filename **is** the document's identity (`doc_key`). Without `WorkPath`, the path handed to the parser is the real, intact one.

### **ParseChunkProcess** (Business Process)

| Setting | Default | Effect |
|---|---|---|
| `ChunkSize` | `512` | Token ceiling per chunk, inherited overlap included. Smaller (128–256) gives sharper passages and higher similarity on pointed questions, at the cost of more chunks and more risk of an answer straddling two. Larger (1024+) carries more context but averages the vector across topics. Measured on the demo corpus: dropping 512 → 192 took the same contract from **6 to 16 chunks**. |
| `ChunkOverlap` | `64` | Tokens from the end of the previous chunk repeated at the start of the next, within the same section. Zero disables it. Above ~25% inflates cost and makes the same passage compete with itself. Must be **smaller** than `ChunkSize` — an equal or larger value is rejected at entry with both values named. |
| `EmbeddingTimeout` | `30` | Seconds to wait for a chunk's embedding. A timeout counts as that chunk's failure, not the document's. |
| `TargetConfigName` | `EmbeddingBridgeOperation` | Item that embeds and persists the chunk. |

### **EmbeddingBridgeOperation** (Business Operation)

| Setting | Default | Effect |
|---|---|---|
| `TargetTable` | `dc_omniIngest.DocumentChunk` | Chunk table as `<schema>.<table>`. Must exist with the embedding config's vector dimension. |
| `EmbeddingConfigName` | `omniingest-default` | Name of the `%Embedding.Config` holding provider, model and credential. **No API key field appears anywhere in this screen.** |

`PoolSize` is **1** on this Operation, and that is not a performance tweak: reingestion bookkeeping lives in job memory and assumes a document's chunks arrive in sequence.

### **Vector dimension follows the provider**

The dimension is not a `dc.omniIngest` choice — it is fixed by the embedding model, and `VECTOR(DOUBLE, n)` fixes `n` at `CREATE TABLE` time.

| Model | Dimension |
|---|---|
| OpenAI `text-embedding-3-small`, `text-embedding-ada-002` | 1536 |
| OpenAI `text-embedding-3-large` | 3072 |
| Cohere `embed-multilingual-v3.0`, `embed-english-v3.0` | 1024 |
| Gemini `text-embedding-004` | 768 |

The package default is **1536**. If your provider differs, create the table with its dimension — which is exactly why the table name is a setting:

```objectscript
Do ##class(dc.omniIngest.Schema).Create("dc_omniIngest.DocumentChunk1024", 1024)
```

Then point `target table` at it. The iFind index follows the table name (`<Table>IFindText`), so the hybrid query becomes `search_index(DocumentChunk1024IFindText, ...)`.

Running `Schema.Create` against an existing table with a different dimension **destroys nothing**: it fails, naming the dimension found and the one expected.

> **Changing a setting while the Production runs is not enough.** A `start` on an already-running Production is a no-op, and items keep their old values — ingestion keeps working and the log still says *"persisted, 0 failed"* while writing to the previous target. Call `update_production()` or stop the Production for real, and confirm by reading the `embedding_config` column of the new rows, not the log.

---

## 🗄️ Chunk Table Schema

Created by `dc.omniIngest.Schema.Create(table, dimension)`, idempotent: if the table already exists with the expected dimension it touches nothing.

| Column | Type | Content |
|---|---|---|
| `id` | `BIGINT IDENTITY` | Primary key. |
| `doc_key` | `VARCHAR(512)` | **Document identity** — the original filename, spaces and accents intact. Reingestion replaces the previous version by this key. |
| `doc_id` | `VARCHAR(64)` | SHA-256 of the content, hex. Tells you whether the file changed — deliberately *not* the identity, since an edited file gets a new hash and would orphan the old version. |
| `source_file` | `VARCHAR(1024)` | Path the file was read from. |
| `chunk_index` | `INTEGER` | Ordinal within the document, zero-based and contiguous. Empty chunks are dropped before numbering. |
| `heading_path` | `VARCHAR(2048)` | Section heading path, `" > "` separated. Empty when the chunk sits under no heading. |
| `page_numbers` | `VARCHAR(256)` | Source pages, ascending, comma-separated (`"3,4"`). Populated for PDF and PPTX (each slide is a page); empty for MD and TXT. |
| `chunk_text` | `VARCHAR(32000)` | **Raw** chunk text. What you display, and what iFind indexes. |
| `chunk_vector` | `VECTOR(DOUBLE, n)` | Embedding of the **contextualized** text (headings + content). |
| `embedding_config` | `VARCHAR(128)` | Which `%Embedding.Config` produced this row — so you know which model each vector came from. |
| `vector_dimension` | `INTEGER` | Dimension actually written. |
| `created_at` | `TIMESTAMP` | Defaults to `CURRENT_TIMESTAMP`. Stored as `%PosixTime`: read raw it returns an integer (`1154711266821846976`); use `CAST(created_at AS VARCHAR(30))` for `2026-09-18 20:10:15`. |

Indexes: `DocumentChunkIFindText` (`%iFind.Index.Basic` over `chunk_text`) and `DocumentChunkIdxDocKey`.

An approximate vector index (HNSW) can be added over `chunk_vector` later with no destructive `ALTER` and no reingestion.

### **Hybrid Search**

Keyword and vector in one statement:

```sql
SELECT TOP 5 doc_key, chunk_index, heading_path, page_numbers, chunk_text,
       VECTOR_COSINE(chunk_vector, TO_VECTOR(?, double, 1024)) AS similarity
FROM dc_omniIngest.DocumentChunk
WHERE %ID %FIND search_index(DocumentChunkIFindText, 'refund')
ORDER BY similarity DESC
```

The parameter is the query vector as a comma-separated string — exactly what `dc.omniIngest.Embedder.EmbedToCsv()` returns.

> In `TO_VECTOR`, the type is a **keyword, not a string**, and neither it nor the dimension accepts a `?` parameter. `TO_VECTOR(?, 'DOUBLE', ?)` fails with *Invalid VECTOR field definition*.

> `GROUP BY doc_key` returns the name in **UPPERCASE** — that is the IRIS `SQLUPPER` collation acting on the grouping, not corruption. A plain `SELECT doc_key` returns it correctly.

---

## 🎬 Demo

A reproducible corpus — one file per supported format, including a PDF with a ruled table built byte by byte — is generated by a script in the repo:

```sh
docker exec omniingest-iris-1 /usr/irissys/bin/irispython \
  /home/irisowner/dev/tests/fixtures/gerar_fixtures.py
```

Drop all five into the watched folder and the event log tells the whole story:

```
arquivo recebido 'apresentacao_politicas.pptx' (30361 bytes, sha256 57aef1e7625a...)
'apresentacao_politicas.pptx' parseado como PPTX em 16 ms.
'apresentacao_politicas.pptx' gerou 3 chunks (chunk_size=512, chunk_overlap=64).
chunk 0 ... persistido na linha 4 de dc_omniIngest.DocumentChunk
resumo de 'apresentacao_politicas.pptx' -- 3 chunks gerados, 3 persistidos, 0 falhos.
```

### **Why hybrid, measured**

Run against a live IRIS with real Cohere `embed-multilingual-v3.0` vectors. Objective criterion: **does the top-1 result contain the answer?**

```
                                      hybrid top-1    vector-only top-1
"What is the refund deadline?"        HIT     0.793   HIT     0.793
"How long does delivery take?"        HIT     0.819   HIT     0.819
"What is the fee to return clothes?"  HIT     0.647   MISS    0.657
TOTAL                                         3/3             2/3
```

Look at the third row. Vector-only search returns, in first place, a chunk scoring **0.657 — higher than the correct answer's 0.647** — that does not contain the answer. What answers the question is the `Clothing | 15 days | 5%` row of the price table, and what brings it is the iFind filter.

Not an artifact of a small corpus: **the same question fails with both models tested** (`embed-multilingual-v3.0` and `embed-english-v3.0`). This is the mirror image of the finding in `dc.omniReRank`'s article — there, a cross-encoder demoted a strong lexical match in favour of a broad semantic reading; here, cosine rewards broad semantic proximity and loses the lexical match that answers the question. Same phenomenon from both sides, and the reason both signals have to coexist on the same row.

---

## 🗂️ Project Structure

```
omniIngest/
├── src/dc/omniIngest/
│   ├── Schema.cls                 # Idempotent DDL · iFind index · capability guard
│   ├── Embedder.cls               # %Embedding.Config dispatch · %Vector → CSV
│   └── Setup.cls                  # Boot: create table · promote Ens.DataType.ConfigName
├── src/python/omni_ingest/
│   ├── messages.py                # IngestFileRequest · ChunkEmbedRequest · ChunkEmbedResponse
│   ├── file_watcher.py            # Business Service · extension filter · doc_key/doc_id
│   ├── parse_chunk.py             # Docling · HybridChunker · contextualize · overlap
│   ├── embedding_bridge.py        # Embed · dimension guard · transactional INSERT · reingest
│   └── production.py              # Production defined in code, not clicked in the UI
├── tests/dc/omniIngest/unittests/
│   └── FakeEmbedding.cls          # Test double — deterministic vector, no network
├── tests/fixtures/
│   ├── gerar_fixtures.py          # Reproducible corpus generator (PDF built by hand)
│   └── *.pdf | *.docx | *.pptx | *.md | *.txt
├── openspec/changes/add-omni-ingest-pipeline/
│   ├── proposal.md                # Why · what changes · impact
│   ├── specs/document-ingestion/  # Behaviour contract — SHALL/MUST, WHEN/THEN
│   ├── design.md                  # Decisions with alternatives · risks with mitigations
│   └── tasks.md                   # 55 tasks, each with its verification criterion
├── module.xml                     # IPM manifest — depends on dc-omni-embedding
├── docker-compose.yml
└── README.md
```

---

## 🧪 Verification

`dc.omniIngest` was built spec-first under [OpenSpec](https://github.com/Fission-AI/OpenSpec). The behaviour contract lives in `openspec/`, and **55 tasks each carry the command, SQL query or observable behaviour that proves them done** — every one executed against a live IRIS 2026.2, not asserted.

Reload a Python module after editing it:

```sh
docker exec omniingest-iris-1 /usr/irissys/bin/irispython \
  /usr/irissys/mgr/python/bin/intersystems_pyprod \
  /home/irisowner/dev/src/python/omni_ingest/parse_chunk.py
```

> The `intersystems_pyprod` CLI runs under `irispython`, **not** `python3` — with the plain interpreter it fails with `No module named 'iris'`.

> Reloading a Python module regenerates its properties as `%VarString` and breaks the Production diagram's arrows. Run `##class(dc.omniIngest.Setup).PromoverAlvosNoDiagrama()` afterwards — the container boot already does.

A `%UnitTest` suite is **not** part of v1 — see Roadmap. What exists today is the OpenSpec verification set, the fixture generator and the embedding test double.

---

## ⚠️ Known Limitations

- **Scanned PDFs yield no text.** OCR is off by design: Docling's default pipeline enables it and EasyOCR downloads its own weights on first conversion, which would break the no-network guarantee. PDFs with a text layer — the common case — work normally.
- **One document at a time.** Chunk-by-chunk synchronous dispatch gives exact accounting and natural back-pressure against provider rate limits, at the cost of a document's latency being the sum of its chunks'.
- **The file is readable only during `OnProcessInput`.** The adapter archives it as soon as the service returns, which is what makes synchronous dispatch mandatory rather than merely preferable.
- **Token counts are estimated**, dividing characters by 3 — deliberately conservative, because exact tokenizers download model files on first use.

---

## 📊 Roadmap

### ✅ **v1.0 — Complete**

* [x] Pure-Python Production via `intersystems_pyprod` — Service, Process, Operation
* [x] Five formats: PDF, DOCX, PPTX, Markdown, TXT (TXT presented to Docling as Markdown — it has no plain-text format)
* [x] Structure-aware chunking: `HybridChunker` + heading contextualization + intra-section overlap
* [x] Offline parsing — CPU-only torch, Docling layout models baked into the image, OCR disabled
* [x] Idempotent DDL with vector-dimension guard and IRIS capability check
* [x] `%iFind.Index.Basic` + native `VECTOR` column on the same row — hybrid search from day one
* [x] Reingestion replaces the previous version atomically; a failed parse leaves the old version serving
* [x] Per-chunk transactional writes and per-chunk failure isolation
* [x] Every setting exposed on the Production screen; no API key anywhere in the UI
* [x] Full message-level observability — file and chunks in one Message Viewer session
* [x] OpenSpec artifacts: proposal, behaviour specs, design decisions, 55 verified tasks

### 🔮 **Future**

* [ ] `%UnitTest` suite against mocked embedding — CI without cloud keys
* [ ] Parallel ingestion — move reingestion state out of job memory to unlock `PoolSize > 1`
* [ ] HNSW index in the shipped schema, once measured at which corpus size it pays off
* [ ] Adaptive chunking per document type — a contract and a slide deck should not share one `chunk_size`
* [ ] Optional exact tokenizer, pre-downloaded into the image
* [ ] Incremental reingestion — skip unchanged documents by `doc_id`

---

## 🎖️ Credits

`dc.omniIngest` is designed and developed with 💜 by:

- [**Henry Pereira**](https://community.intersystems.com/user/henry-pereira) — architecture, implementation, testing

Companion libraries — together they close the RAG pipeline **ingest → embed → hybrid search → rerank**:

- [**`dc.omniEmbedding`**](https://github.com/henryhamon/omniEmbedding) — the universal embedding gateway this package dispatches to
- [**`dc.omniReRank`**](https://github.com/henryhamon/omniRerank) — the universal reranking gateway that orders the results this package makes searchable

The three are architecturally independent, sharing only the IRIS-native `%Embedding.Config` store.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
