"""持久化基础设施：数据库、事务和仓储适配。"""

from infra.persistence.sqlite import SQLiteDatabase

__all__ = ["SQLiteDatabase"]
