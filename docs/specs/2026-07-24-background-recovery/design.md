# Design

SQLite 初始化时原子将遗留 `running` 记录标记为 `interrupted`，不自动重放未知副作用任务。
