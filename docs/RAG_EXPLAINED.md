# How the RAG system works

A study guide for explaining this project's RAG (retrieval-augmented generation) pipeline, for example in
job interviews. Numbers come from the code and the eval results (`evals/`, first runs 2026-11-06).

## The 30-second pitch

> "My app makes narrated history videos. Instead of letting the LLM research from memory or browse the web
> turn by turn, I built a RAG pipeline: code downloads 10-15 real sources per topic, splits them into
> overlapping chunks, embeds them with Gemini and stores them in Postgres with pgvector. Retrieval is hybrid
> (vector similarity plus Postgres full-text search, merged with reciprocal rank fusion). The retrieved
> passages ground the research brief, the script, chat edits and a fact-check step. A second RAG pipeline
> powers a public site, where viewers can search videos by meaning and ask a chatbot questions answered with
> clickable timestamps. I measured it with my own eval suite: 100% of answers had the right passage in the
> top 6, 93% of answers were grounded in the passages, and research used 91% fewer input tokens than the
> web-browsing approach."

## The big picture

```
 INGEST (once per topic)                      RETRIEVE                      GENERATE
 -----------------------                      --------                      --------
 Wikipedia API + web pages                question / brief section       Claude (studio)
        |  download in parallel                   |                       - research brief
        v                                         v                       - script
 clean text (trafilatura)                 embed query (Gemini)            - chat edits
        |                                         |                       - fact check
        v                                +--------+--------+
 chunks: ~300 words, 50 overlap          vector search   keyword search    Gemini Flash-Lite (site)
        |                                (pgvector)      (Postgres FTS)    - chatbot with [m:ss]
        v                                +--------+--------+
 embed (Gemini, 768 dims)                 merge with reciprocal rank fusion
        |                                         |
        v                                         v
 Supabase Postgres + pgvector  --------->  top passages ----------------->  prompt
```

## 1. Ingestion: getting sources into the database

1. **Find sources:**
   - Wikipedia's API returns 4-8 articles.
   - Claude does about 3 quick web searches and suggests 6-10 more URLs from archives, museums,
     universities and news sites. It only picks links and doesn't read the pages.
2. **Download in parallel** with httpx. **trafilatura** strips menus and ads, leaving the article text.
   Pages under about 300 words are skipped, and duplicate URLs are removed. (`backend/pipeline/sources.py`)
3. **Chunk:** about 300 words per chunk, with about 50 words of overlap. (`chunking.py`)
   - Chunks break at paragraph and sentence ends, never mid-sentence.
   - The overlap keeps a fact that sits on a boundary whole in at least one chunk.
   - Each chunk keeps its document title and section heading.
4. **Embed** with Google's `gemini-embedding-001`: 768 dimensions, batches of 100, free tier. (`embeddings.py`)
   - Stored chunks use the `RETRIEVAL_DOCUMENT` task type and questions use `RETRIEVAL_QUERY`, because the
     model tunes the vectors differently for each.
5. **Store** in Supabase Postgres with the pgvector extension. (`vector_store.py`, `backend/supabase/schema.sql`)
   - Tables: `documents` (one row per URL), `chunks` (text, a `vector(768)` column, and a generated
     `tsvector` column for keyword search) and `project_documents` (which video used which source).
   - Indexes: **HNSW** on the vectors for fast approximate nearest-neighbour search, and **GIN** on the
     tsvector for full-text search.
   - **Dedup:** if a URL already exists with the same text hash, it isn't embedded again. That's how the
     corpus grows and gets reused across videos.

## 2. Retrieval: hybrid search

Each query runs two searches:
- **Vector search:** cosine distance (`<=>`) in pgvector. It finds passages with the same *meaning*, even
  when the wording differs.
- **Keyword search:** Postgres `websearch_to_tsquery` plus `ts_rank`. It catches exact names, dates and rare
  words that embeddings can blur.

The two ranked lists are merged with **reciprocal rank fusion (RRF)**: each passage scores `1/(60 + rank)`
in each list, and the scores are added. RRF uses rank positions instead of raw scores, so you never have to
balance cosine similarity against ts_rank numbers.

**Multi-query retrieval:** research runs one query per section of the brief (timeline, key people, causes
and so on). The top results from each query are taken in turn (round-robin), so every section gets passages.

**Shared corpus:** a new project searches its own sources first. Then it can borrow up to 4 passages from
other videos' sources, but only when they're a close match (similarity of 0.8 or more).

## 3. Generation: where the passages are used

| Step | What gets retrieved | What Claude does |
|---|---|---|
| Research brief | ~30 passages, one query per brief section | Writes a cited fact sheet ([1], [2]...) from the passages only, with no tools |
| Script | ~10 passages for the brief's key facts and turning points | Writes the script from the brief, checking details against the passages |
| Chat edit | 5 passages that match the request | Any new fact must come from them |
| Check facts | 2 passages per script paragraph (up to 24) | Flags claims that are wrong or that nothing confirms, and suggests fixes |

**Why it's faster and cheaper:** the old way had Claude browse for 26 turns, re-reading the whole
conversation every turn (282k input tokens). Now code does the downloading, and Claude makes one or two
calls with no tools (26k tokens).

## 4. The second pipeline: the public site's chatbot

- **Ingest:** when a video is published, its narration is cut into **30-45 second windows** that end on
  sentence boundaries. Each window keeps its start and end time from the voice-over's word timings, and each
  is embedded and stored. (`backend/pipeline/site_publish.py`)
- **Retrieve:** a viewer's question pulls the top 6 narration windows, the windows around the moment they're
  watching, and the top 3 research passages. (`site/server/app.py`)
- **Generate:** Gemini Flash-Lite answers from that context and cites moments like `[3:42]`, which the page
  turns into links that jump the YouTube player there.
- **Search bar:** the same hybrid search over all videos returns each video's best matching moment.

## 5. Guard rails and security

- **Relevance check before the LLM is called:** if the question's similarity to the video is under 0.55,
  it's refused for free. In the eval, real questions scored 0.58-0.81, and junk like "make me a Chipotle
  bowl" scored 0.45-0.60.
- **Prompt rules:** visitor text is treated as a question only, so no role-play and no revealing the
  instructions. Google's safety filters are also turned on.
- **Keys:** the model only ever sees the instructions and the passages. The API key goes in a request
  header, errors shown to visitors are generic, and the database user is **read-only**.
- **Cost:** the Gemini key's project has billing turned off, so the worst case is a "too many requests"
  error, never a bill. There are also per-visitor and site-wide rate limits and an answer cache.

## 6. Evaluation

Three eval layers run on real data (`evals/`), plus a speed test:
1. **Retrieval** (questions generated from known passages):
   - The right narration window was in the top 6 results **100%** of the time, and first **88%** of the time.
   - Hybrid search was compared against vector-only search.
2. **Answer quality** (Claude grades the answers):
   - **93% grounded** and **100% correct**.
   - **43 of 43** timestamps pointed to real passages.
   - **83%** of questions the video doesn't cover were handled correctly. That's the known weak spot.
3. **Guard rails:** **0 of 54** real questions were refused, and **61 of 80** attacks were blocked by the
   free check. Of the 19 that got through, the model declined 18.
4. **Speed and tokens:** research was **39% faster** with **91% fewer input tokens**. The full comparison
   (research, script, fact check and revision on both sides) is built but not run yet.

## Likely interview questions

- **Why hybrid search instead of vectors only?** Embeddings are weak on exact names and dates, and keyword
  search is weak on paraphrases. RRF combines both without tuning weights.
- **Why 300-word chunks with overlap?** Big enough to hold a full fact with context, small enough that
  retrieval stays precise. The overlap stops facts from being split across chunk boundaries.
- **Why pgvector instead of Pinecone or another vector DB?** One Postgres database holds the vectors, the
  full-text index and the normal tables. It's free on Supabase, and SQL joins and filters (like "only this
  project's sources") just work.
- **How do you prevent hallucination?** The prompts say to use only the given material and to cite sources.
  The fact check verifies claims against the stored passages. The evals measure groundedness.
- **What would you improve?**
  - Add a reranker (a cross-encoder) after RRF.
  - Fix the 83% "doesn't cover that" score.
  - Move the rate limits to a shared store like Redis, since serverless instances don't share memory.
  - Finish the full speed benchmark.
- **Honest trade-off:** RAG didn't make *script writing* faster, because that step is dominated by Claude
  writing about 1,650 words, and RAG adds passages to read. The win is in research, cost and accuracy.
