from __future__ import annotations

import json
import logging
import math
import shutil
from pathlib import Path

import httpx

from agent.config.loader import Config
from agent.db.database import Database
from agent.db.knowledge_docs_repo import KnowledgeDocsRepository
from agent.runtime.protocols import OutputHandler

logger = logging.getLogger(__name__)


class _VectorStore:
    """
    Flat JSON vector store with cosine similarity search.
    No external dependencies — fast enough for expedition-scale KB (<2000 chunks).
    """

    def __init__(self, path: str) -> None:
        self._dir = Path(path)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._store_path = self._dir / "store.json"

    def _load(self) -> dict:
        if self._store_path.exists():
            return json.loads(self._store_path.read_text(encoding="utf-8"))
        return {"ids": [], "embeddings": [], "documents": [], "metadatas": []}

    def _save(self, store: dict) -> None:
        self._store_path.write_text(json.dumps(store), encoding="utf-8")

    def count(self) -> int:
        return len(self._load()["ids"])

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        store = self._load()
        id_index = {id_: idx for idx, id_ in enumerate(store["ids"])}
        for i, id_ in enumerate(ids):
            if id_ in id_index:
                idx = id_index[id_]
                store["embeddings"][idx] = embeddings[i]
                store["documents"][idx] = documents[i]
                store["metadatas"][idx] = metadatas[i]
            else:
                store["ids"].append(id_)
                store["embeddings"].append(embeddings[i])
                store["documents"].append(documents[i])
                store["metadatas"].append(metadatas[i])
        self._save(store)

    def query(self, query_embedding: list[float], n_results: int) -> dict:
        store = self._load()
        if not store["ids"]:
            return {"documents": [[]], "metadatas": [[]]}

        def _cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na and nb else 0.0

        scores = [_cosine(query_embedding, emb) for emb in store["embeddings"]]
        top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n_results]
        return {
            "documents": [[store["documents"][i] for i in top]],
            "metadatas": [[store["metadatas"][i] for i in top]],
        }

    def clear(self) -> None:
        if self._store_path.exists():
            self._store_path.unlink()


class KnowledgeService:
    def __init__(self, config: Config, db: Database, output: OutputHandler | None = None) -> None:
        self._cfg = config.knowledge
        self._ollama_url = config.photo_pipeline.ollama_url
        self._db = db
        self._output = output

    def _progress(self, msg: str) -> None:
        if self._output:
            self._output.on_task_progress(msg)

    def _chunk(self, text: str) -> list[str]:
        size = self._cfg.chunk_size
        overlap = self._cfg.chunk_overlap
        chunks: list[str] = []
        start = 0
        while start < len(text):
            chunks.append(text[start : start + size].strip())
            start += size - overlap
        return [c for c in chunks if c]

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient() as client:
            # Try batch endpoint first (Ollama >= 0.1.26)
            resp = await client.post(
                f"{self._ollama_url}/api/embed",
                json={"model": self._cfg.embedding_model, "input": texts},
                timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
            )
            if resp.status_code == 404:
                # Fall back to legacy endpoint — one request per text
                embeddings = []
                for text in texts:
                    r = await client.post(
                        f"{self._ollama_url}/api/embeddings",
                        json={"model": self._cfg.embedding_model, "prompt": text},
                        timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
                    )
                    r.raise_for_status()
                    embeddings.append(r.json()["embedding"])
                return embeddings
            resp.raise_for_status()
        return resp.json()["embeddings"]

    async def index_documents(self) -> int:
        inbox_dir = Path(self._cfg.inbox_dir)
        processed_dir = Path(self._cfg.processed_dir)
        processed_dir.mkdir(parents=True, exist_ok=True)

        if not inbox_dir.exists():
            return 0

        docs = list(inbox_dir.glob("*.txt")) + list(inbox_dir.glob("*.md"))
        if not docs:
            return 0

        store = _VectorStore(self._cfg.chroma_dir)
        repo = KnowledgeDocsRepository(self._db)
        total_chunks = 0

        for doc_path in docs:
            await repo.insert(doc_path.name)
            text = doc_path.read_text(encoding="utf-8", errors="ignore")
            chunks = self._chunk(text)
            if not chunks:
                await repo.mark_failed(doc_path.name, "empty document")
                continue

            self._progress(f"indexing {doc_path.name}: {len(chunks)} chunks")
            try:
                embeddings = await self._embed(chunks)
                ids = [f"{doc_path.stem}_{i}" for i in range(len(chunks))]
                store.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=chunks,
                    metadatas=[{"source": doc_path.name}] * len(chunks),
                )
                total_chunks += len(chunks)
                await repo.mark_indexed(doc_path.name, len(chunks))
                shutil.move(str(doc_path), processed_dir / doc_path.name)
                self._progress(f"moved {doc_path.name} → processed/")
            except Exception as exc:
                await repo.mark_failed(doc_path.name, str(exc))
                logger.error("Failed to index %s: %s", doc_path.name, exc)

        logger.info("Indexed %d chunks from %d documents", total_chunks, len(docs))
        return total_chunks

    async def add_document(self, content: str, title: str = "inline") -> int:
        chunks = self._chunk(content)
        if not chunks:
            return 0
        embeddings = await self._embed(chunks)
        store = _VectorStore(self._cfg.chroma_dir)
        ids = [f"{title}_{i}" for i in range(len(chunks))]
        store.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=[{"source": title}] * len(chunks),
        )
        return len(chunks)

    async def search(self, query: str, n_results: int | None = None) -> str:
        n = n_results or self._cfg.n_results
        store = _VectorStore(self._cfg.chroma_dir)

        if store.count() == 0:
            return "knowledge base is empty — run index_knowledge first"

        embeddings = await self._embed([query])
        results = store.query(embeddings[0], n_results=n)

        docs = results["documents"][0]
        metadatas = results["metadatas"][0]

        if not docs:
            return "no relevant knowledge found"

        parts = []
        for doc, meta in zip(docs, metadatas):
            source = meta.get("source", "unknown") if meta else "unknown"
            parts.append(f"[{source}]\n{doc}")
        return "\n\n---\n\n".join(parts)

    async def clear(self) -> None:
        _VectorStore(self._cfg.chroma_dir).clear()
        await KnowledgeDocsRepository(self._db).clear_all()
        logger.info("Knowledge base cleared")
