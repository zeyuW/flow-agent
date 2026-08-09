"""向量记忆存储：SQLite 元数据 + sqlite-vec 扩展。

功能特性：
- 内容哈希去重
- 强化机制
- 使用 sqlite-vec 进行向量相似度搜索
- 批量替换操作
- consolidation_events 支持
- memory_replacements 支持
- 线程安全操作
"""

import hashlib
import json
import logging
import math
import re
import sqlite3
import struct
import threading
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

from application.memory.domain.models import MemoryItem
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

try:
    import sqlite_vec
    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    _SQLITE_VEC_AVAILABLE = False

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

VEC_DIM = 1024
_LOCAL_TZ = timezone(timedelta(hours=8))
_P = ParamSpec("_P")
_R = TypeVar("_R")

_MEMORY_ITEMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding TEXT,
    reinforcement INTEGER NOT NULL DEFAULT 1,
    emotional_weight INTEGER NOT NULL DEFAULT 0,
    extra_json TEXT,
    source_ref TEXT,
    happened_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _compute_content_hash(text: str, memory_type: str) -> str:
    """计算内容哈希用于去重。"""
    normalized = re.sub(r"\s+", " ", text.lower().strip()) + memory_type
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _now_iso() -> str:
    """获取当前时间的 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _synchronized(method: Callable[_P, _R]) -> Callable[_P, _R]:
    """串行化共享 SQLite 连接上的所有存储操作。"""
    @wraps(method)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        store = cast("MemoryStore", args[0])
        with store._lock:
            return method(*args, **kwargs)
    return wrapped


def _normalize_emb(emb: list[float]) -> list[float]:
    """L2 归一化，供 vec_items 存储用。"""
    if not _NUMPY_AVAILABLE:
        return emb
    v = np.array(emb, dtype=np.float32)
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return emb
    return (v / n).tolist()


def _emb_to_blob(emb: list[float]) -> bytes:
    """将归一化后的 embedding 打包为 float32 blob。"""
    normed = _normalize_emb(emb)
    return struct.pack(f"{len(normed)}f", *normed)


def _l2dist_to_cosine(distance: float) -> float:
    """将单位球上的 L2 距离转换回 cosine similarity。"""
    return 1.0 - (distance * distance) / 2.0


class MemoryStore:
    """向量记忆存储：SQLite 元数据 + sqlite-vec 扩展。

    使用 SQLite 存储元数据，sqlite-vec 进行向量相似度搜索。
    如果 sqlite-vec 不可用，则回退到纯 Python 向量搜索。
    线程安全，使用共享连接和锁机制。
    """

    def __init__(self, db_path: Path, vec_dim: int = VEC_DIM) -> None:
        self.db_path = db_path
        self.vec_dim = vec_dim
        self._use_vec = _SQLITE_VEC_AVAILABLE
        self._vec_enabled = False
        self._vec_init_error: str | None = None
        self._lock = threading.RLock()
        self._closed = False
        
        # 创建共享连接
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        """初始化数据库架构，支持 sqlite-vec。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # 主表架构
            self._db.executescript(_MEMORY_ITEMS_TABLE_SQL + """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_items_hash
                    ON memory_items (content_hash, memory_type);
                CREATE TABLE IF NOT EXISTS consolidation_events (
                    source_ref TEXT PRIMARY KEY,
                    item_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_replacements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    old_item_id TEXT NOT NULL,
                    old_memory_type TEXT NOT NULL,
                    old_summary TEXT NOT NULL,
                    old_source_ref TEXT,
                    old_happened_at TEXT,
                    old_extra_json TEXT,
                    new_item_id TEXT NOT NULL,
                    new_memory_type TEXT NOT NULL,
                    new_summary TEXT NOT NULL,
                    new_source_ref TEXT,
                    new_happened_at TEXT,
                    new_extra_json TEXT,
                    relation_type TEXT NOT NULL DEFAULT 'supersede',
                    source_ref TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_memory_replacements_old_item
                    ON memory_replacements (old_item_id, created_at);
                CREATE INDEX IF NOT EXISTS ix_memory_replacements_new_item
                    ON memory_replacements (new_item_id, created_at);
                CREATE INDEX IF NOT EXISTS ix_items_status ON memory_items (status);
            """)
            self._db.commit()
            logger.info("数据库主表架构初始化成功")
        except Exception as exc:
            logger.error(f"数据库主表架构初始化失败: {exc}")
            raise
        
        # sqlite-vec 初始化
        if self._use_vec:
            try:
                self._db.enable_load_extension(True)
                sqlite_vec.load(self._db)
                self._db.enable_load_extension(False)
                vec_schema = f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(
                    embedding float[{self.vec_dim}]
                );
                """
                self._db.executescript(vec_schema)
                self._db.commit()
                self._vec_enabled = True
                self._migrate_existing_to_vec()
                logger.info("sqlite-vec 已启用（dim=%d）", self.vec_dim)
            except Exception as exc:
                self._vec_enabled = False
                self._vec_init_error = str(exc)
                logger.warning("sqlite-vec 初始化失败（%s），回退到全表扫描", exc)
        else:
            self._vec_init_error = "sqlite_vec 未安装"
            logger.debug("sqlite-vec 未安装，使用全表扫描")

    def _migrate_existing_to_vec(self) -> None:
        """启动时迁移缺失的向量索引，失败时回滚本轮迁移。"""
        existing = {r[0] for r in self._db.execute("SELECT rowid FROM vec_items").fetchall()}
        rows = self._db.execute(
            "SELECT rowid, embedding FROM memory_items WHERE embedding IS NOT NULL"
        ).fetchall()
        migrated = 0
        self._db.execute("BEGIN")
        try:
            for rowid, emb_json in rows:
                if rowid in existing:
                    continue
                try:
                    emb = json.loads(emb_json) if emb_json else None
                    if emb is None or len(emb) != self.vec_dim:
                        continue
                    self._db.execute(
                        "INSERT INTO vec_items(rowid, embedding) VALUES (?, ?)",
                        (rowid, _emb_to_blob(emb)),
                    )
                    migrated += 1
                except (json.JSONDecodeError, TypeError):
                    continue
            self._db.commit()
        except (ValueError, OverflowError, sqlite3.Error, struct.error):
            self._db.rollback()
            raise
        if migrated:
            logger.info("sqlite-vec: 迁移了 %d 条历史 embedding", migrated)

    def _vec_insert(self, rowid: int, emb: list[float]) -> None:
        """向 vec_items 插入一条向量（幂等：先删再插）。维度不匹配时静默跳过。"""
        if not self._vec_enabled or len(emb) != self.vec_dim:
            return
        try:
            self._db.execute("DELETE FROM vec_items WHERE rowid=?", (rowid,))
            self._db.execute(
                "INSERT INTO vec_items(rowid, embedding) VALUES (?, ?)",
                (rowid, _emb_to_blob(emb)),
            )
        except sqlite3.Error as exc:
            self._disable_vec("写入", exc)

    def _vec_delete(self, rowids: list[int]) -> None:
        """从 vec_items 批量删除。"""
        if not self._vec_enabled or not rowids:
            return
        try:
            self._db.executemany(
                "DELETE FROM vec_items WHERE rowid=?", [(r,) for r in rowids]
            )
        except sqlite3.Error as exc:
            self._disable_vec("删除", exc)

    def _disable_vec(self, operation: str, exc: sqlite3.Error) -> None:
        self._vec_enabled = False
        self._vec_init_error = f"sqlite-vec {operation}失败: {exc}"
        logger.warning(
            "sqlite-vec %s失败（%s），后续检索回退到全表扫描",
            operation,
            exc,
        )

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._closed:
            return
        try:
            self._db.close()
        finally:
            self._closed = True

    def __del__(self) -> None:
        self.close()

    @_synchronized
    def write(
        self,
        memory_type: str,
        summary: str,
        embedding: list[float] | None = None,
        source_ref: str = "",
        emotional_weight: int = 0,
        happened_at: str = "",
        extra: dict[str, Any] | None = None,
    ) -> MemoryItem:
        """写入记忆条目，支持去重和强化。

        如果相同 content_hash 存在且为 active，则 reinforcement+1；
        如果存在但为 superseded，则重新激活并 reinforcement+1；
        如果不存在，则新建。
        """
        content_hash = _compute_content_hash(summary, memory_type)
        now = _now_iso()
        embedding_payload = json.dumps(embedding) if embedding else None
        extra_json = json.dumps(extra) if extra else None

        existing = self._db.execute(
            "SELECT id, status FROM memory_items WHERE content_hash=? AND memory_type=?",
            (content_hash, memory_type),
        ).fetchone()

        if existing:
            item_id, status = existing
            if status == "superseded":
                self._db.execute(
                    "UPDATE memory_items SET status='active', reinforcement=reinforcement+1, updated_at=?, emotional_weight=MAX(emotional_weight, ?) WHERE id=?",
                    (now, emotional_weight, item_id),
                )
            else:
                self._db.execute(
                    "UPDATE memory_items SET reinforcement=reinforcement+1, updated_at=?, emotional_weight=MAX(emotional_weight, ?) WHERE id=?",
                    (now, emotional_weight, item_id),
                )
            self._db.commit()
            
            # 获取更新后的数据
            row = self._db.execute(
                "SELECT id, memory_type, summary, embedding, content_hash, reinforcement, emotional_weight, status, source_ref, happened_at, extra_json, created_at, updated_at FROM memory_items WHERE id=?",
                (item_id,),
            ).fetchone()
            return self._row_to_item(row)

        # 新建记录
        item_id = hashlib.md5(f"{content_hash}{time.time()}".encode()).hexdigest()[:12]
        cur = self._db.execute(
            """INSERT INTO memory_items
               (id, memory_type, summary, content_hash, embedding, emotional_weight,
                extra_json, source_ref, happened_at, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (item_id, memory_type, summary, content_hash, embedding_payload, emotional_weight,
             extra_json, source_ref, happened_at, now, now),
        )
        item_rowid = cur.lastrowid
        self._db.commit()

        if embedding is not None and item_rowid is not None:
            self._vec_insert(item_rowid, embedding)
            self._db.commit()

        # 获取新建的数据
        row = self._db.execute(
            "SELECT id, memory_type, summary, embedding, content_hash, reinforcement, emotional_weight, status, source_ref, happened_at, extra_json, created_at, updated_at FROM memory_items WHERE id=?",
            (item_id,),
        ).fetchone()
        return self._row_to_item(row)

    def _row_to_item(self, row) -> MemoryItem:
        """将数据库行转换为 MemoryItem。"""
        (
            item_id, memory_type, summary, embedding_payload, content_hash,
            reinforcement, emotional_weight, status, source_ref,
            happened_at, extra_json, created_at, updated_at
        ) = row
        
        embedding = json.loads(embedding_payload) if embedding_payload else None
        extra = json.loads(extra_json) if extra_json else {}
        
        return MemoryItem(
            id=str(item_id),
            memory_type=memory_type,
            summary=summary,
            embedding=embedding,
            content_hash=content_hash,
            reinforcement=reinforcement,
            emotional_weight=int(emotional_weight or 0),
            status=status,
            source_ref=source_ref or "",
            happened_at=happened_at or "",
            extra_json=extra,
            created_at=str(created_at or ""),
            updated_at=str(updated_at or ""),
        )

    @_synchronized
    def mark_superseded_batch(self, item_ids: list[str]) -> None:
        """批量标记记忆条目为已替换。"""
        if not item_ids:
            return
        now = _now_iso()
        self._db.executemany(
            "UPDATE memory_items SET status='superseded', updated_at=? WHERE id=?",
            [(now, item_id) for item_id in item_ids],
        )
        self._db.commit()
        
        # 获取对应的 rowid 并删除向量索引
        rowids = []
        for item_id in item_ids:
            row = self._db.execute("SELECT rowid FROM memory_items WHERE id=?", (item_id,)).fetchone()
            if row:
                rowids.append(row[0])
        if rowids:
            self._vec_delete(rowids)
            self._db.commit()

    @_synchronized
    def list_active(self, memory_type: str | None = None) -> list[MemoryItem]:
        """列出所有 active 状态的记忆条目。"""
        if memory_type:
            rows = self._db.execute(
                """
                SELECT id, memory_type, summary, embedding, content_hash,
                       reinforcement, emotional_weight, status, source_ref,
                       happened_at, extra_json, created_at, updated_at
                FROM memory_items
                WHERE status = 'active' AND memory_type = ?
                ORDER BY reinforcement DESC, updated_at DESC
                """,
                (memory_type,),
            ).fetchall()
        else:
            rows = self._db.execute(
                """
                SELECT id, memory_type, summary, embedding, content_hash,
                       reinforcement, emotional_weight, status, source_ref,
                       happened_at, extra_json, created_at, updated_at
                FROM memory_items
                WHERE status = 'active'
                ORDER BY reinforcement DESC, updated_at DESC
                """
            ).fetchall()
        
        return [self._row_to_item(row) for row in rows]

    @_synchronized
    def search_by_ids(self, item_ids: list[str]) -> list[MemoryItem]:
        """按 ID 列表查询记忆条目。"""
        if not item_ids:
            return []
        placeholders = ",".join("?" for _ in item_ids)
        rows = self._db.execute(
            f"""
            SELECT id, memory_type, summary, embedding, content_hash,
                   reinforcement, emotional_weight, status, source_ref,
                   happened_at, extra_json, created_at, updated_at
            FROM memory_items
            WHERE id IN ({placeholders})
            """,
            item_ids,
        ).fetchall()
        return [self._row_to_item(row) for row in rows]

    @_synchronized
    def search_by_source_ref(self, source_ref: str) -> list[MemoryItem]:
        """按 source_ref 查询记忆条目（用于幂等检查）。"""
        rows = self._db.execute(
            """
            SELECT id, memory_type, summary, embedding, content_hash,
                   reinforcement, emotional_weight, status, source_ref,
                   happened_at, extra_json, created_at, updated_at
            FROM memory_items
            WHERE source_ref = ?
            """,
            (source_ref,),
        ).fetchall()
        return [self._row_to_item(row) for row in rows]

    @_synchronized
    def count_active(self) -> int:
        """统计 active 状态总数。"""
        row = self._db.execute(
            "SELECT COUNT(*) FROM memory_items WHERE status = 'active'"
        ).fetchone()
        return int(row[0]) if row else 0

    @_synchronized
    def vector_search(
        self,
        query_embedding: list[float],
        top_k: int = 8,
        memory_type: str | None = None,
        score_threshold: float = 0.0,
    ) -> list[tuple[MemoryItem, float]]:
        """使用 sqlite-vec 或回退方案进行向量相似度搜索。

        返回按相似度排序的 (MemoryItem, score) 元组列表。
        """
        if self._vec_enabled:
            return self._vector_search_vec(query_embedding, top_k, memory_type, score_threshold)
        else:
            return self._vector_search_fallback(query_embedding, top_k, memory_type, score_threshold)

    def _vector_search_vec(
        self,
        query_embedding: list[float],
        top_k: int,
        memory_type: str | None,
        score_threshold: float,
    ) -> list[tuple[MemoryItem, float]]:
        """使用 sqlite-vec 扩展进行向量搜索。"""
        query_blob = _emb_to_blob(query_embedding)

        if memory_type:
            rows = self._db.execute(
                """
                SELECT mi.id, mi.memory_type, mi.summary, mi.embedding,
                       mi.content_hash, mi.reinforcement, mi.emotional_weight,
                       mi.status, mi.source_ref, mi.happened_at, mi.extra_json,
                       mi.created_at, mi.updated_at, distance
                FROM memory_items mi
                JOIN vec_items mv ON mi.rowid = mv.rowid
                WHERE mi.status = 'active' AND mi.memory_type = ?
                AND mi.embedding IS NOT NULL
                AND mv.embedding MATCH ?
                AND k = ?
                ORDER BY distance
                """,
                (memory_type, query_blob, top_k * 2),
            ).fetchall()
        else:
            rows = self._db.execute(
                """
                SELECT mi.id, mi.memory_type, mi.summary, mi.embedding,
                       mi.content_hash, mi.reinforcement, mi.emotional_weight,
                       mi.status, mi.source_ref, mi.happened_at, mi.extra_json,
                       mi.created_at, mi.updated_at, distance
                FROM memory_items mi
                JOIN vec_items mv ON mi.rowid = mv.rowid
                WHERE mi.status = 'active'
                AND mi.embedding IS NOT NULL
                AND mv.embedding MATCH ?
                AND k = ?
                ORDER BY distance
                """,
                (query_blob, top_k * 2),
            ).fetchall()

        results = []
        for row in rows:
            item = self._row_to_item(row[:13])
            distance = row[13]
            if distance is not None:
                score = _l2dist_to_cosine(distance)
                if score >= score_threshold:
                    results.append((item, score))

        return sorted(results, key=lambda x: x[1], reverse=True)[:top_k]

    def _vector_search_fallback(
        self,
        query_embedding: list[float],
        top_k: int,
        memory_type: str | None,
        score_threshold: float,
    ) -> list[tuple[MemoryItem, float]]:
        """使用纯 Python 进行回退向量搜索。"""
        if not _NUMPY_AVAILABLE:
            return []
            
        items = self.list_active(memory_type)
        if not items:
            return []

        query_vec = np.array(query_embedding, dtype=np.float32)
        query_vec = query_vec / np.linalg.norm(query_vec)

        results = []
        for item in items:
            if not item.embedding:
                continue
            item_vec = np.array(item.embedding, dtype=np.float32)
            item_vec = item_vec / np.linalg.norm(item_vec)
            score = float(np.dot(query_vec, item_vec))
            if score >= score_threshold:
                results.append((item, score))

        return sorted(results, key=lambda x: x[1], reverse=True)[:top_k]

    @_synchronized
    def upsert_consolidation_event(
        self,
        *,
        source_ref: str,
        summary: str,
        embedding: list[float] | None,
        extra: dict[str, Any] | None = None,
        happened_at: str = "",
        emotional_weight: int = 0,
    ) -> str:
        """原子写入 consolidation event：同一 source_ref 最多写一次。"""
        src = (source_ref or "").strip()
        text = (summary or "").strip()
        if not src or not text:
            return "skipped:empty"

        self._db.execute("BEGIN IMMEDIATE")
        new_item_rowid: int | None = None
        new_item_emb: list[float] | None = None
        try:
            already = self._db.execute(
                "SELECT item_id FROM consolidation_events WHERE source_ref=?",
                (src,),
            ).fetchone()
            if already is not None:
                self._db.execute("COMMIT")
                existing_id = already[0] or ""
                return f"skipped:{existing_id or src}"

            chash = _compute_content_hash(text, "event")
            existing = self._db.execute(
                "SELECT id, status FROM memory_items WHERE content_hash=? AND memory_type=?",
                (chash, "event"),
            ).fetchone()

            now = _now_iso()
            if existing:
                row_id, status = existing
                if status == "superseded":
                    self._db.execute(
                        "UPDATE memory_items SET status='active', reinforcement=reinforcement+1, updated_at=?, emotional_weight=MAX(emotional_weight, ?), happened_at=COALESCE(NULLIF(happened_at, ''), ?) WHERE id=?",
                        (now, emotional_weight, happened_at, row_id),
                    )
                else:
                    self._db.execute(
                        "UPDATE memory_items SET reinforcement=reinforcement+1, updated_at=?, emotional_weight=MAX(emotional_weight, ?), happened_at=COALESCE(NULLIF(happened_at, ''), ?) WHERE id=?",
                        (now, emotional_weight, happened_at, row_id),
                    )
                item_id = row_id
                result = f"reinforced:{row_id}"
            else:
                item_id = hashlib.md5(f"{chash}{time.time()}".encode()).hexdigest()[:12]
                embedding_payload = json.dumps(embedding) if embedding else None
                extra_json = json.dumps(extra) if extra else None
                cur = self._db.execute(
                    """INSERT INTO memory_items
                       (id, memory_type, summary, content_hash, embedding, emotional_weight,
                        extra_json, source_ref, happened_at, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (item_id, "event", text, chash, embedding_payload, emotional_weight,
                     extra_json, src, happened_at, now, now),
                )
                new_item_rowid = cur.lastrowid
                new_item_emb = embedding
                result = f"new:{item_id}"

            self._db.execute(
                "INSERT INTO consolidation_events(source_ref, item_id, created_at) VALUES (?, ?, ?)",
                (src, item_id, now),
            )
            self._db.execute("COMMIT")

            if new_item_rowid is not None and new_item_emb is not None:
                self._vec_insert(new_item_rowid, new_item_emb)
                self._db.commit()

            return result
        except Exception:
            try:
                self._db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise

    @_synchronized
    def has_consolidation_source_ref(self, source_ref: str) -> bool:
        """检查是否已存在该 source_ref 的 consolidation event。"""
        row = self._db.execute(
            "SELECT 1 FROM consolidation_events WHERE source_ref=? LIMIT 1",
            ((source_ref or "").strip(),),
        ).fetchone()
        return row is not None

    @_synchronized
    def record_replacements(
        self,
        *,
        old_items: list[dict[str, Any]],
        new_item: dict[str, Any],
        source_ref: str | None = None,
        relation_type: str = "supersede",
    ) -> int:
        """记录记忆替换关系。"""
        if not old_items or not new_item or not new_item.get("id"):
            return 0
        now = _now_iso()
        rows = []
        for old_item in old_items:
            if not old_item or not old_item.get("id"):
                continue
            rows.append(
                (
                    str(old_item.get("id")),
                    str(old_item.get("memory_type") or ""),
                    str(old_item.get("summary") or ""),
                    old_item.get("source_ref"),
                    old_item.get("happened_at"),
                    json.dumps(old_item.get("extra_json") or {}, ensure_ascii=False),
                    str(new_item.get("id")),
                    str(new_item.get("memory_type") or ""),
                    str(new_item.get("summary") or ""),
                    new_item.get("source_ref"),
                    new_item.get("happened_at"),
                    json.dumps(new_item.get("extra_json") or {}, ensure_ascii=False),
                    relation_type,
                    source_ref or new_item.get("source_ref"),
                    now,
                )
            )
        if not rows:
            return 0
        self._db.executemany(
            """INSERT INTO memory_replacements
               (old_item_id, old_memory_type, old_summary, old_source_ref, old_happened_at,
                old_extra_json, new_item_id, new_memory_type, new_summary, new_source_ref,
                new_happened_at, new_extra_json, relation_type, source_ref, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        self._db.commit()
        return len(rows)

    @_synchronized
    def list_replacements(self) -> list[dict]:
        """列出所有记忆替换关系。"""
        rows = self._db.execute(
            "SELECT old_item_id, old_memory_type, old_summary, old_source_ref, "
            "old_happened_at, old_extra_json, new_item_id, new_memory_type, "
            "new_summary, new_source_ref, new_happened_at, new_extra_json, "
            "relation_type, source_ref, created_at "
            "FROM memory_replacements ORDER BY id ASC"
        ).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "old_item_id": row[0],
                    "old_memory_type": row[1],
                    "old_summary": row[2],
                    "old_source_ref": row[3],
                    "old_happened_at": row[4],
                    "old_extra_json": json.loads(row[5]) if row[5] else {},
                    "new_item_id": row[6],
                    "new_memory_type": row[7],
                    "new_summary": row[8],
                    "new_source_ref": row[9],
                    "new_happened_at": row[10],
                    "new_extra_json": json.loads(row[11]) if row[11] else {},
                    "relation_type": row[12],
                    "source_ref": row[13],
                    "created_at": row[14],
                }
            )
        return result
