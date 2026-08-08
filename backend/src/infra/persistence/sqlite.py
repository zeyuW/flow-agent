"""SQLite 持久化基础设施。

该模块只负责连接生命周期和事务边界，不包含任何业务表结构或仓储逻辑。
业务模块应在自己的 infra 层定义仓储，并通过本模块获得数据库连接。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterator


class SQLiteDatabase:
    """提供线程安全的 SQLite 连接和显式事务。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
        )
        self._lock = RLock()
        self._closed = False

    @property
    def connection(self) -> sqlite3.Connection:
        """返回连接对象，供仓储执行查询或配置连接。"""

        if self._closed:
            raise RuntimeError("SQLite 数据库连接已经关闭")
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """开启事务，成功提交，异常回滚并继续抛出。"""

        with self._lock:
            connection = self.connection
            connection.execute("BEGIN")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def close(self) -> None:
        """关闭连接；重复关闭不会产生副作用。"""

        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def __enter__(self) -> "SQLiteDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
