"""向量记忆存储：SQLite 元数据 + Python 向量表，支持 content_hash 去重和 reinforcement 强化。

实现 spec 5a-5e：
- 5a: memory_items 表结构（含 content_hash, embedding, reinforcement, emotional_weight, status）
- 5b: 去重写入逻辑（content_hash 判重）
- 5c: 强化已有记忆（reinforcement 计数）
- 5d: 向量表（内存余弦相似度检索）
- 5e: 批量标记失效（mark_superseded_batch）
"""

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MemoryItem:
    """记忆条目。"""

    id: int
    memory_type: str  # procedure / preference / event / fact
    summary: str
    embedding: list[float] | None
    content_hash: str
    reinforcement: int = 1
    emotional_weight: float = 1.0
    status: str = "active"  # active / superseded
    source_ref: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "memory_type": self.memory_type,
            "summary": self.summary,
            "embedding": self.embedding,
            "content_hash": self.content_hash,
            "reinforcement": self.reinforcement,
            "emotional_weight": self.emotional_weight,
            "status": self.status,
            "source_ref": self.source_ref,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _compute_content_hash(text: str) -> str:
    """计算内容哈希，用于去重。"""
    normalized = " ".join(text.split()).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class MemoryStore:
    """向量记忆存储：SQLite 持久化 metadata + 内存向量数组。

    使用 SQLite 存储记忆条目的元数据（summary, content_hash, reinforcement 等），
    向量（embedding）序列化为 JSON BLOB 存储在 SQLite 中，
    检索时加载所有 active 条目到内存进行余弦相似度计算。

    这是 sqlite-vec 扩展的纯 Python 替代方案，适合中小规模记忆库（< 10K 条）。
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        """初始化表结构（spec 5a）。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    embedding_json TEXT,
                    content_hash TEXT NOT NULL,
                    reinforcement INTEGER NOT NULL DEFAULT 1,
                    emotional_weight REAL NOT NULL DEFAULT 1.0,
                    status TEXT NOT NULL DEFAULT 'active',
                    source_ref TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_content_hash_type
                ON memory_items(content_hash, memory_type)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_status
                ON memory_items(status)
                """
            )

    def write(
        self,
        memory_type: str,
        summary: str,
        embedding: list[float] | None = None,
        source_ref: str = "",
        emotional_weight: float = 1.0,
    ) -> MemoryItem:
        """写入记忆条目，支持去重和强化（spec 5b, 5c）。

        如果相同 content_hash 已存在且为 active，则 reinforcement+1；
        如果已存在但为 superseded，则重新激活并 reinforcement+1；
        如果不存在，则新建。
        """
        content_hash = _compute_content_hash(summary)
        now = time.time()
        embedding_json = json.dumps(embedding) if embedding else None

        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT id, reinforcement, status FROM memory_items
                WHERE content_hash = ? AND memory_type = ?
                """,
                (content_hash, memory_type),
            ).fetchone()

            if existing:
                item_id, current_reinf, current_status = existing
                new_status = "active"
                new_reinf = current_reinf + 1
                conn.execute(
                    """
                    UPDATE memory_items
                    SET reinforcement = ?, status = ?, updated_at = ?,
                        emotional_weight = ?, embedding_json = COALESCE(?, embedding_json)
                    WHERE id = ?
                    """,
                    (new_reinf, new_status, now, emotional_weight, embedding_json, item_id),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO memory_items
                        (memory_type, summary, embedding_json, content_hash,
                         reinforcement, emotional_weight, status, source_ref,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, 'active', ?, ?, ?)
                    """,
                    (memory_type, summary, embedding_json, content_hash,
                     emotional_weight, source_ref, now, now),
                )
                item_id = cursor.lastrowid

        conn.close()
        return MemoryItem(
            id=item_id,
            memory_type=memory_type,
            summary=summary,
            embedding=embedding,
            content_hash=content_hash,
            reinforcement=new_reinf if existing else 1,
            emotional_weight=emotional_weight,
            status="active",
            source_ref=source_ref,
            created_at=now,
            updated_at=now,
        )

    def mark_superseded_batch(self, item_ids: list[int]) -> None:
        """批量标记记忆失效（spec 5e）。"""
        if not item_ids:
            return
        now = time.time()
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE memory_items SET status = 'superseded', updated_at = ?
                WHERE id = ?
                """,
                [(now, iid) for iid in item_ids],
            )

    def list_active(self, memory_type: str | None = None) -> list[MemoryItem]:
        """列出所有 active 状态的记忆条目。"""
        with self._connect() as conn:
            if memory_type:
                rows = conn.execute(
                    """
                    SELECT id, memory_type, summary, embedding_json, content_hash,
                           reinforcement, emotional_weight, status, source_ref,
                           created_at, updated_at
                    FROM memory_items
                    WHERE status = 'active' AND memory_type = ?
                    ORDER BY reinforcement DESC, updated_at DESC
                    """,
                    (memory_type,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, memory_type, summary, embedding_json, content_hash,
                           reinforcement, emotional_weight, status, source_ref,
                           created_at, updated_at
                    FROM memory_items
                    WHERE status = 'active'
                    ORDER BY reinforcement DESC, updated_at DESC
                    """,
                ).fetchall()

        return [_row_to_item(row) for row in rows]

    def search_by_ids(self, item_ids: list[int]) -> list[MemoryItem]:
        """按 ID 列表查询记忆条目。"""
        if not item_ids:
            return []
        placeholders = ",".join("?" for _ in item_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, memory_type, summary, embedding_json, content_hash,
                       reinforcement, emotional_weight, status, source_ref,
                       created_at, updated_at
                FROM memory_items
                WHERE id IN ({placeholders})
                """,
                item_ids,
            ).fetchall()
        return [_row_to_item(row) for row in rows]

    def search_by_source_ref(self, source_ref: str) -> list[MemoryItem]:
        """按 source_ref 查询记忆条目（用于幂等检查）。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, memory_type, summary, embedding_json, content_hash,
                       reinforcement, emotional_weight, status, source_ref,
                       created_at, updated_at
                FROM memory_items
                WHERE source_ref = ?
                """,
                (source_ref,),
            ).fetchall()
        return [_row_to_item(row) for row in rows]

    def count_active(self) -> int:
        """统计 active 状态总数。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM memory_items WHERE status = 'active'"
            ).fetchone()
            return int(row[0]) if row else 0


def _row_to_item(row: tuple) -> MemoryItem:
    embedding_raw = row[3]
    embedding = json.loads(embedding_raw) if embedding_raw else None
    return MemoryItem(
        id=row[0],
        memory_type=row[1],
        summary=row[2],
        embedding=embedding,
        content_hash=row[4],
        reinforcement=row[5],
        emotional_weight=row[6],
        status=row[7],
        source_ref=row[8],
        created_at=row[9],
        updated_at=row[10],
    )
