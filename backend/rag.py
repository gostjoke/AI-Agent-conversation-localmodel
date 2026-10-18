"""
RAG as agent tools — PostgreSQL only (pgvector + full-text). No Milvus/Qdrant.
RAG 包成 agent 工具 —— 只用 PostgreSQL（pgvector 語意 + 全文檢索關鍵字），不另架向量庫。

Pipeline 流程:
  query ─┬─ keyword: tsvector (jieba 斷詞 + 'simple' config)  → ranked list A  關鍵字（精確字詞、料號）
         └─ vector : pgvector cosine (Ollama embeddings)     → ranked list B  語意（RAG_MODE=hybrid）
         → RRF merge 融合 → optional cross-encoder rerank 重排序 (bge-reranker) → top_k

Modes 模式 (env RAG_MODE):
  keyword  keyword only + agent multi-round search (default; enough for a few hundred docs)
           純關鍵字 + agent 多輪查詢（預設；幾百份文件通常夠用）
  hybrid   keyword + vector. After switching run `python rag.py embed` to fill vectors.
           關鍵字 + 向量；切換後執行 `python rag.py embed` 補上向量

CLI 指令:
  python backend/rag.py ingest <folder|file>   index files (incremental, sha256) 匯入（增量）
  python backend/rag.py embed                  embed rows missing vectors 補向量
  python backend/rag.py search "query"         test search 測試搜尋
  python backend/rag.py sources                list indexed files 已索引檔案
  python backend/rag.py reset                  drop table (e.g. after changing embed dim) 刪表重建
"""

import hashlib
import logging
import os
import re
import sys
import threading
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# ── Config 設定 ───────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")                # postgresql://agent:agent@localhost:5432/agent
RAG_MODE = os.getenv("RAG_MODE", "keyword").lower()         # keyword | hybrid
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "bge-m3")        # multilingual 中英皆可; dim 1024
EMBED_DIM = int(os.getenv("RAG_EMBED_DIM", "1024"))         # must match model 必須與模型維度一致
RERANKER = os.getenv("RAG_RERANKER", "")                    # e.g. BAAI/bge-reranker-v2-m3 ; "" = off 關閉
CHUNK_CHARS = int(os.getenv("RAG_CHUNK_CHARS", "800"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "120"))
CANDIDATES = 30          # per retriever before merge 每路召回數
RRF_K = 60               # Reciprocal Rank Fusion constant 融合常數
MAX_SNIPPET = 1200       # chars per hit sent to model 每筆回傳字數上限

TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".sql", ".py", ".log", ".html", ".htm",
            ".xml", ".yaml", ".yml", ".ini", ".cfg"}
DOC_EXT = TEXT_EXT | {".pdf", ".docx"}

STOPWORDS = set("的 了 是 在 和 與 与 及 或 有 嗎 吗 呢 吧 啊 怎麼 怎么 如何 什麼 什么 請 请 我 你 他 這 这 那 "
                "哪 個 个 要 會 会 能 可以 一下 the a an of to in on is are was for and or how what "
                "which who do does please".split())


# ── DB helpers 資料庫 ─────────────────────────────────────────────────────────
def _connect(timeout: int = 5):
    import psycopg
    return psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=timeout)


_schema_ok = False


def ensure_schema() -> None:
    """Create extension/table/indexes once. 首次自動建表與索引。"""
    global _schema_ok
    if _schema_ok:
        return
    with _connect() as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS rag_chunks (
              id         bigserial PRIMARY KEY,
              source     text NOT NULL,
              chunk_no   int  NOT NULL,
              content    text NOT NULL,
              tsv        tsvector NOT NULL,
              embedding  vector({EMBED_DIM}),          -- NULL in keyword mode 關鍵字模式為 NULL
              sha        text NOT NULL,
              updated_at timestamptz DEFAULT now(),
              UNIQUE (source, chunk_no))""")
        c.execute("CREATE INDEX IF NOT EXISTS rag_chunks_tsv ON rag_chunks USING gin (tsv)")
        c.execute("CREATE INDEX IF NOT EXISTS rag_chunks_emb ON rag_chunks "
                  "USING hnsw (embedding vector_cosine_ops)")
        row = c.execute("SELECT atttypmod FROM pg_attribute WHERE attrelid='rag_chunks'::regclass "
                        "AND attname='embedding'").fetchone()
        if row and row[0] not in (-1, EMBED_DIM):
            raise RuntimeError(f"rag_chunks.embedding is vector({row[0]}) but RAG_EMBED_DIM={EMBED_DIM}. "
                               "Run `python rag.py reset` then re-ingest. 維度不符，請 reset 後重新匯入")
    _schema_ok = True


# ── Text processing 文字處理 ──────────────────────────────────────────────────
_jieba = None


_CJK_RUN = re.compile(r"[㐀-鿿豈-﫿]{2,}")


def _seg(text: str) -> list[str]:
    """Tokens = jieba words + CJK bigrams (bigrams fix 繁體 segmentation with jieba's default dict).
    詞元 = jieba 斷詞 + 中文二元組（彌補 jieba 預設詞典對繁體斷詞不準）。"""
    global _jieba
    if _jieba is None:
        import jieba
        jieba.setLogLevel(logging.WARNING)
        _jieba = jieba
    toks = [t for t in (w.strip().lower() for w in _jieba.cut_for_search(text))
            if t and re.fullmatch(r"\w+", t)]
    for run in _CJK_RUN.findall(text):
        toks += [run[i:i + 2] for i in range(len(run) - 1)]
    return toks


def _tsv_text(text: str) -> str:
    return " ".join(_seg(text))


def _query_tokens(q: str) -> list[str]:
    seen, out = set(), []
    for t in _seg(q):
        if t not in STOPWORDS and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Paragraph-aware chunking with overlap. 依段落切塊，含重疊。"""
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    for p in paras:  # hard-split very long paragraphs 過長段落硬切
        while len(p) > size:
            pieces.append(p[:size])
            p = p[size - overlap:]
        pieces.append(p)
    chunks, buf = [], ""
    for p in pieces:
        if buf and len(buf) + len(p) + 2 > size:
            chunks.append(buf)
            buf = buf[-overlap:] + "\n" + p if overlap else p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        chunks.append(buf)
    return chunks


def read_document(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader  # pip install pypdf
        return "\n\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)
    if ext == ".docx":
        import docx  # pip install python-docx
        return "\n\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    return path.read_text(encoding="utf-8", errors="replace")


# ── Embeddings (Ollama) 向量 ──────────────────────────────────────────────────
def embed(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    with httpx.Client(timeout=300) as cl:
        for i in range(0, len(texts), 32):
            r = cl.post(f"{OLLAMA_BASE_URL}/api/embed", json={"model": EMBED_MODEL, "input": texts[i:i + 32]})
            r.raise_for_status()
            out += r.json()["embeddings"]
    return out


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


# ── Ingest 匯入 ───────────────────────────────────────────────────────────────
def ingest_path(target: Path, root: Path | None = None) -> str:
    """Index a file or folder (incremental by sha256). 匯入檔案/資料夾（內容沒變就略過）。"""
    ensure_schema()
    target = target.resolve()
    root = (root or (target if target.is_dir() else target.parent)).resolve()
    files = [target] if target.is_file() else sorted(
        p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in DOC_EXT)
    added = skipped = failed = chunks_total = 0
    use_vec = RAG_MODE == "hybrid"
    with _connect() as c:
        for f in files:
            src = f.relative_to(root).as_posix()
            try:
                text = read_document(f)
            except Exception as e:
                failed += 1
                log.warning("skip %s: %s", src, e)
                continue
            sha = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
            if c.execute("SELECT 1 FROM rag_chunks WHERE source=%s AND sha=%s LIMIT 1", (src, sha)).fetchone():
                skipped += 1
                continue
            chunks = chunk_text(text)
            vecs: list = [None] * len(chunks)
            if use_vec and chunks:
                try:
                    vecs = [_vec(v) for v in embed([f"{src}\n{ch}" for ch in chunks])]
                except Exception as e:  # keep keyword index; fill later with `embed` 先存關鍵字，之後補向量
                    log.warning("embed failed for %s (%s); run `python rag.py embed` later", src, e)
            with c.transaction():
                c.execute("DELETE FROM rag_chunks WHERE source=%s", (src,))
                for i, (ch, v) in enumerate(zip(chunks, vecs)):
                    # tsv = raw text (keeps codes like PN-123-A) + jieba tokens (CJK words)
                    # 原文（保留料號等複合詞）+ jieba 斷詞（中文詞）; source name is searchable too
                    c.execute(
                        "INSERT INTO rag_chunks (source, chunk_no, content, tsv, embedding, sha) VALUES "
                        "(%s,%s,%s, to_tsvector('simple', %s) || to_tsvector('simple', %s), %s::vector, %s)",
                        (src, i, ch, f"{src} {ch}", _tsv_text(f"{src} {ch}"), v, sha))
            added += 1
            chunks_total += len(chunks)
    return (f"Indexed {added} file(s), {chunks_total} chunks; unchanged {skipped}; failed {failed}. "
            f"已匯入 {added} 檔 / {chunks_total} 塊，未變更 {skipped}，失敗 {failed}。 (mode={RAG_MODE})")


def embed_missing() -> str:
    """Fill embeddings for rows that have none. 為缺向量的資料補上向量。"""
    ensure_schema()
    n = 0
    with _connect() as c:
        while True:
            rows = c.execute("SELECT id, source, content FROM rag_chunks WHERE embedding IS NULL "
                             "ORDER BY id LIMIT 64").fetchall()
            if not rows:
                break
            vecs = embed([f"{s}\n{t}" for _, s, t in rows])
            for (rid, _, _), v in zip(rows, vecs):
                c.execute("UPDATE rag_chunks SET embedding=%s::vector WHERE id=%s", (_vec(v), rid))
            n += len(rows)
    return f"Embedded {n} chunks 已補 {n} 塊向量"


# ── Search 檢索 ───────────────────────────────────────────────────────────────
def _keyword(c, q: str, src_filter: str, n: int) -> list[tuple]:
    toks = _query_tokens(q) or _seg(q)
    if not toks:
        return []
    tsq = " | ".join(toks)  # OR query; tokens are \w+ only → safe 只含字元，安全
    return c.execute(
        "SELECT id, source, chunk_no, content FROM rag_chunks, to_tsquery('simple', %s) q "
        "WHERE tsv @@ q AND source ILIKE %s ORDER BY ts_rank_cd(tsv, q, 1) DESC LIMIT %s",
        (tsq, f"%{src_filter}%", n)).fetchall()


def _vector(c, q: str, src_filter: str, n: int) -> list[tuple]:
    try:
        qv = _vec(embed([q])[0])
    except Exception as e:
        log.warning("query embed failed, keyword only: %s", e)
        return []
    return c.execute(
        "SELECT id, source, chunk_no, content FROM rag_chunks WHERE embedding IS NOT NULL "
        "AND source ILIKE %s ORDER BY embedding <=> %s::vector LIMIT %s",
        (f"%{src_filter}%", qv, n)).fetchall()


_reranker = None
_rr_lock = threading.Lock()


def _rerank(q: str, hits: list[dict]) -> list[dict]:
    """Cross-encoder rerank (sentence-transformers). 交叉編碼器重排序；未安裝則略過。"""
    global _reranker
    if not RERANKER or len(hits) < 2:
        return hits
    try:
        with _rr_lock:
            if _reranker is None:
                from sentence_transformers import CrossEncoder  # pip install -r requirements-rerank.txt
                _reranker = CrossEncoder(RERANKER, max_length=512)
                log.info("reranker loaded: %s", RERANKER)
            scores = _reranker.predict([(q, h["content"]) for h in hits])
    except Exception as e:
        log.warning("rerank skipped: %s", e)
        return hits
    for h, s in zip(hits, scores):
        h["score"] = float(s)
    return sorted(hits, key=lambda h: h["score"], reverse=True)


def search(query: str, top_k: int = 5, source: str = "") -> list[dict]:
    ensure_schema()
    with _connect() as c:
        lists = [_keyword(c, query, source, CANDIDATES)]
        if RAG_MODE == "hybrid":
            lists.append(_vector(c, query, source, CANDIDATES))
    fused: dict[int, dict] = {}
    for lst in lists:  # RRF: score = Σ 1/(k + rank)
        for rank, (rid, src, no, content) in enumerate(lst, 1):
            h = fused.setdefault(rid, {"source": src, "chunk": no, "content": content, "score": 0.0})
            h["score"] += 1.0 / (RRF_K + rank)
    hits = sorted(fused.values(), key=lambda h: h["score"], reverse=True)
    hits = _rerank(query, hits[:max(top_k * 4, 20)]) if RERANKER else hits
    return hits[:top_k]


def format_hits(query: str, hits: list[dict]) -> str:
    if not hits:
        return (f"No results for '{query}'. Retry with other keywords: synonyms, English/中文, exact codes, "
                "or call list_doc_sources. 查無結果，請換關鍵字（同義詞、中英文、料號）再查。")
    out = [f"[{i}] {h['source']}#{h['chunk']} (score {h['score']:.3f})\n{h['content'][:MAX_SNIPPET]}"
           for i, h in enumerate(hits, 1)]
    return "\n\n".join(out) + "\n\n(Cite as [source#chunk]. If not enough, search again with refined keywords.)"


def list_sources(flt: str = "") -> str:
    ensure_schema()
    with _connect() as c:
        rows = c.execute("SELECT source, count(*), count(embedding) FROM rag_chunks WHERE source ILIKE %s "
                         "GROUP BY source ORDER BY source LIMIT 200", (f"%{flt}%",)).fetchall()
    if not rows:
        return "(no indexed documents 尚無索引文件)"
    return "\n".join(f"{s}  ({n} chunks{', ' + str(e) + ' embedded' if e else ''})" for s, n, e in rows)


# ── Agent tools 註冊為 agent 工具 ─────────────────────────────────────────────
def register_tools() -> bool:
    """Register tools only if DB reachable. 只有連得到資料庫才註冊工具。"""
    if not DATABASE_URL:
        log.info("RAG disabled (DATABASE_URL not set) 未設定 DATABASE_URL，RAG 停用")
        return False
    try:
        with _connect(timeout=2):
            pass
        ensure_schema()
    except Exception as e:
        log.warning("RAG disabled, DB unreachable 資料庫連不到: %s", e)
        return False

    from tools import WORKSPACE, _safe_path, tool

    @tool("search_docs",
          "Search the internal knowledge base (SOPs, specs, manuals, notes) by keywords. Returns chunks "
          "with [source#chunk] citations. Use for any question about internal documents. If results are "
          "weak, call again with different keywords: synonyms, both English and Chinese, exact part/PO "
          "numbers or error codes. Prefer short keyword queries over full sentences.",
          {"query": {"type": "string", "description": "Keywords, e.g. 'IQC 退料 流程' or 'MRP run error'"},
           "top_k": {"type": "integer", "description": "Results to return, default 5 (max 10)"},
           "source": {"type": "string", "description": "Optional filename filter, e.g. 'SOP' or '.pdf'"}},
          ["query"], label="搜尋文件 Search docs")
    def search_docs(query: str, top_k: int = 5, source: str = "") -> str:
        return format_hits(query, search(query, max(1, min(int(top_k or 5), 10)), source or ""))

    @tool("list_doc_sources", "List indexed documents in the knowledge base (optionally filtered by name).",
          {"filter": {"type": "string", "description": "Optional filename substring"}},
          label="文件清單 List docs")
    def list_doc_sources(filter: str = "") -> str:  # noqa: A002 (name shown to model)
        return list_sources(filter or "")

    @tool("index_documents",
          "Add/refresh files from the agent workspace into the knowledge base (txt, md, csv, pdf, docx...). "
          "Unchanged files are skipped.",
          {"path": {"type": "string", "description": "Relative file or folder in workspace, default '.'"}},
          label="建立索引 Index docs")
    def index_documents(path: str = ".") -> str:
        return ingest_path(_safe_path(path), root=WORKSPACE)

    log.info("RAG tools enabled (mode=%s, reranker=%s)", RAG_MODE, RERANKER or "off")
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not DATABASE_URL:
        sys.exit("Set DATABASE_URL first 請先設定 DATABASE_URL")
    cmd, *rest = sys.argv[1:] or ["help"]
    if cmd == "ingest" and rest:
        print(ingest_path(Path(rest[0])))
    elif cmd == "embed":
        print(embed_missing())
    elif cmd == "search" and rest:
        print(format_hits(rest[0], search(rest[0], int(rest[1]) if len(rest) > 1 else 5)))
    elif cmd == "sources":
        print(list_sources())
    elif cmd == "reset":
        with _connect() as conn:
            conn.execute("DROP TABLE IF EXISTS rag_chunks")
        print("rag_chunks dropped 已刪除")
    else:
        print(__doc__)
