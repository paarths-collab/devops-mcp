"""
Long-term memory module for OctaClaw MCP.
Handles SQLite persistence and semantic search via sentence-transformers.
"""

import os
import sqlite3
import hashlib
import json
import re
import numpy as np
from typing import Any, Dict, List, Optional


def _model_cached_locally(model_name: str = "all-MiniLM-L6-v2") -> bool:
    """Check if the sentence-transformer model is already cached locally."""
    home = os.path.expanduser("~")
    # sentence-transformers cache
    st_cache = os.path.join(home, ".cache", "torch", "sentence_transformers", model_name)
    if os.path.isdir(st_cache):
        return True
    # huggingface hub cache (transformers >= 4.22 style)
    hf_cache = os.path.join(home, ".cache", "huggingface", "hub")
    if os.path.isdir(hf_cache):
        # Look for any snapshot dir containing the model name
        for root, dirs, _ in os.walk(hf_cache):
            if model_name.replace("/", "_") in root or model_name in root:
                return True
    return False


# Try to import sentence-transformers; if unavailable or network-blocked,
# fall back to a deterministic hash-based embedding for demo/resilience.
try:
    from sentence_transformers import SentenceTransformer
    _ST_AVAILABLE = True
except Exception:
    _ST_AVAILABLE = False


class _FallbackEmbedder:
    """
    Deterministic fallback embedder when sentence-transformers can't load.
    Uses SHA-256 hashed random projections to produce 384-dim unit vectors.
    Not semantically meaningful, but allows the system to function end-to-end.
    """

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def encode(self, text: str, **kwargs) -> np.ndarray:
        # Deterministic hash -> seed -> random projection
        h = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(h[:4], "big")
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(self.dim).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec


class LongTermMemory:
    """
    SQLite-backed memory with sentence-transformer embeddings.
    Stores structured facts as JSON fields with embeddings on the issue text.
    """

    _shared_model = None

    def __init__(
        self,
        db_path: str = "data/memory.db",
        model_name: str = "all-MiniLM-L6-v2",
        similarity_threshold: float = 0.85,
    ) -> None:
        self.db_path = db_path
        self.similarity_threshold = similarity_threshold
        self._embedding_source = "sentence-transformers"

        if LongTermMemory._shared_model is not None:
            self.model = LongTermMemory._shared_model
        elif _ST_AVAILABLE and _model_cached_locally(model_name):
            try:
                LongTermMemory._shared_model = SentenceTransformer(model_name)
                self.model = LongTermMemory._shared_model
            except Exception:
                self.model = _FallbackEmbedder(dim=384)
                self._embedding_source = "fallback-hash"
        else:
            self.model = _FallbackEmbedder(dim=384)
            self._embedding_source = "fallback-hash"

        self._init_db()
        self._columns = self._get_columns()

    def _init_db(self) -> None:
        """Initialize SQLite database with facts table."""
        # Ensure directory exists for persistent files
        if self.db_path != ":memory:":
            dir_name = os.path.dirname(self.db_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

        # For :memory:, we MUST keep a persistent connection open
        if self.db_path == ":memory:":
            self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
            conn = self._connection
        else:
            self._connection = None
            conn = sqlite3.connect(self.db_path, timeout=10)

        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue TEXT NOT NULL,
                fix TEXT,
                context TEXT,
                tags TEXT,
                embedding BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        self._ensure_schema_conn(conn)
        
        if self._connection is None:
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """Helper to get a connection (reusing if :memory:)."""
        if self.db_path == ":memory:" and self._connection:
            return self._connection
        return sqlite3.connect(self.db_path, timeout=10)

    def _get_columns(self) -> List[str]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(facts)")
        cols = [row[1] for row in cursor.fetchall()]
        if self.db_path != ":memory:":
            conn.close()
        return cols

    def _ensure_schema(self) -> None:
        """Add missing columns to the facts table without dropping data."""
        conn = self._get_conn()
        self._ensure_schema_conn(conn)
        if self.db_path != ":memory:":
            conn.close()

    def _ensure_schema_conn(self, conn: sqlite3.Connection) -> None:
        """Internal: Add missing columns using an existing connection."""
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(facts)")
        existing = {row[1] for row in cursor.fetchall()}

        # Add missing columns to support JSON-structured memory
        if "fix" not in existing:
            cursor.execute("ALTER TABLE facts ADD COLUMN fix TEXT")
        if "context" not in existing:
            cursor.execute("ALTER TABLE facts ADD COLUMN context TEXT")
        if "tags" not in existing:
            cursor.execute("ALTER TABLE facts ADD COLUMN tags TEXT")
        if "resolution" not in existing:
            cursor.execute("ALTER TABLE facts ADD COLUMN resolution TEXT")
        if "repo_name" not in existing:
            cursor.execute("ALTER TABLE facts ADD COLUMN repo_name TEXT")
        if "created_at" not in existing:
            cursor.execute(
                "ALTER TABLE facts ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            )

        conn.commit()

    def embed(self, text: str) -> np.ndarray:
        """
        Convert text to a dense vector embedding.
        Returns a normalized numpy array for cosine similarity.
        """
        embedding = self.model.encode(text, convert_to_numpy=True)
        # Ensure numpy float32
        if not isinstance(embedding, np.ndarray):
            embedding = np.array(embedding, dtype=np.float32)
        # Normalize to unit vector so dot product = cosine similarity
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding.astype(np.float32)

    def add_memory(self, memory: Dict[str, Any]) -> int:
        """
        Embed and store a structured JSON memory.
        Expected keys: issue, fix, context, tags
        Returns the inserted row ID. If a duplicate exists (same issue text), returns existing ID.
        """
        issue = str(memory.get("issue", "")).strip()
        fix = str(memory.get("fix", "")).strip()
        context = str(memory.get("context", "")).strip()
        repo_name = str(memory.get("repo_name", "")).strip()
        tags = memory.get("tags", [])

        if not issue:
            raise ValueError("Memory 'issue' must be a non-empty string.")

        # Duplicate check: exact issue text match
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM facts WHERE issue = ?", (issue,))
        existing = cursor.fetchone()
        if existing:
            if self.db_path != ":memory:":
                conn.close()
            return existing[0]

        embedding = self.embed(issue)
        embedding_bytes = embedding.tobytes()
        tags_json = json.dumps(tags) if isinstance(tags, list) else json.dumps([str(tags)])

        # Insert while preserving legacy columns if present
        columns = self._get_columns()
        values: Dict[str, Any] = {
            "issue": issue,
            "fix": fix,
            "context": context,
            "repo_name": repo_name,
            "tags": tags_json,
            "embedding": embedding_bytes,
        }
        if "resolution" in columns:
            values["resolution"] = fix

        insert_cols = [c for c in values.keys() if c in columns]
        placeholders = ", ".join(["?"] * len(insert_cols))
        col_list = ", ".join(insert_cols)

        cursor.execute(
            f"INSERT INTO facts ({col_list}) VALUES ({placeholders})",
            tuple(values[c] for c in insert_cols),
        )
        row_id = cursor.lastrowid
        conn.commit()
        if self.db_path != ":memory:":
            conn.close()
        return row_id

    def add_fact(self, issue: str, resolution: str) -> int:
        """
        Backward-compatible wrapper for legacy callers.
        """
        return self.add_memory(
            {
                "issue": issue,
                "fix": resolution,
                "context": "",
                "tags": [],
            }
        )

    def _chunk_text(self, text: str, max_len: int = 280) -> List[str]:
        """
        Chunk text into sentence-like segments for more stable similarity.
        """
        cleaned = re.sub(r"\s+", " ", text.strip())
        if not cleaned:
            return []

        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        chunks: List[str] = []
        buf = ""

        for sent in sentences:
            if not sent:
                continue
            if len(buf) + len(sent) + 1 <= max_len:
                buf = f"{buf} {sent}".strip()
            else:
                if buf:
                    chunks.append(buf)
                buf = sent

        if buf:
            chunks.append(buf)

        # Fallback: ensure at least one chunk
        return chunks or [cleaned[:max_len]]

    def _parse_tags(self, tags: Optional[str]) -> List[str]:
        if not tags:
            return []
        try:
            parsed = json.loads(tags)
            if isinstance(parsed, list):
                return [str(t) for t in parsed]
            return [str(parsed)]
        except json.JSONDecodeError:
            return [tags]

    def search_memory(self, query: str, top_k: int = 3, repo_filter: Optional[str] = None) -> List[Dict]:
        """
        Semantic search against all stored facts.
        Returns list of dicts with full JSON fields and similarity score.
        """
        chunks = self._chunk_text(query)
        if not chunks:
            return []

        query_embeddings = [self.embed(c) for c in chunks]

        conn = self._get_conn()
        cursor = conn.cursor()
        
        query_sql = "SELECT id, issue, fix, context, tags, resolution, repo_name, embedding FROM facts"
        params = []
        if repo_filter:
            query_sql += " WHERE repo_name = ?"
            params.append(repo_filter)
            
        cursor.execute(query_sql, params)
        rows = cursor.fetchall()
        if self.db_path != ":memory:":
            conn.close()

        if not rows:
            return []

        results: List[tuple] = []
        for row in rows:
            row_id, issue, fix, context, tags, resolution, repo_name, embedding_bytes = row
            stored_embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
            # Cosine similarity = dot product of normalized vectors
            score = max(float(np.dot(qe, stored_embedding)) for qe in query_embeddings)
            results.append((row_id, issue, fix, context, tags, resolution, repo_name, score))

        # Sort by score descending
        results.sort(key=lambda x: x[7], reverse=True)

        # Return top_k
        output: List[Dict] = []
        for row_id, issue, fix, context, tags, resolution, repo_name, score in results[:top_k]:
            resolved_fix = fix or resolution or ""
            output.append(
                {
                    "id": row_id,
                    "issue": issue,
                    "fix": resolved_fix,
                    "context": context or "",
                    "repo_name": repo_name or "",
                    "tags": self._parse_tags(tags),
                    "score": round(score, 4),
                    # Backward compatibility for callers expecting 'resolution'
                    "resolution": resolved_fix,
                }
            )
        return output

    def get_best_match(self, query: str) -> Optional[Dict]:
        """
        Return the single best match if score >= threshold, else None.
        """
        results = self.search_memory(query, top_k=1)
        if results and results[0]["score"] >= self.similarity_threshold:
            return results[0]
        return None

    def list_facts(self, limit: int = 50, repo_filter: Optional[str] = None) -> List[Dict]:
        """Debug helper: list all stored facts, optionally filtered by repo."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        query = "SELECT id, issue, fix, context, tags, resolution, created_at, repo_name FROM facts"
        params = []
        if repo_filter:
            query += " WHERE repo_name = ?"
            params.append(repo_filter)
            
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        if self.db_path != ":memory:":
            conn.close()

        output: List[Dict] = []
        for r in rows:
            resolved_fix = r[2] or r[5] or ""
            output.append(
                {
                    "id": r[0],
                    "issue": r[1],
                    "fix": resolved_fix,
                    "context": r[3] or "",
                    "tags": self._parse_tags(r[4]),
                    "created_at": r[6],
                    "repo_name": r[7] or "",
                    "resolution": resolved_fix,
                }
            )
        return output

    def get_indexed_repos(self) -> List[str]:
        """Return a unique list of repository names stored in memory."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT repo_name FROM facts WHERE repo_name IS NOT NULL AND repo_name != ''")
        repos = [r[0] for r in cursor.fetchall()]
        if self.db_path != ":memory:":
            conn.close()
        return repos

    def clear_all(self) -> None:
        """Dangerous: wipe all memories."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM facts")
        conn.commit()
        if self.db_path != ":memory:":
            conn.close()
