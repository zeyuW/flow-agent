# Design

执行队列保存内部请求对象而非裸任务名。请求在开始执行前带有 `cancelled` 标记；取消 API 只标记尚未开始执行的同名请求。worker 执行前检查标记并跳过，不创建新的运行记录。

`run_job` 使用现有 `RetryPolicy`。每次异常先调用 `classify_error`：仅 `retryable=True` 且仍有剩余次数时，持久化 `retrying` 状态、记录观测事件并按配置的延迟/倍率等待；否则持久化失败终态。

运行时接收可选 recorder，通过单一 `_record` 方法增加统一时间字段后调用其 `record`。持久化写入仍只经过 `JobStoreWriter`；观测失败隔离并记录日志，不影响任务执行或状态写入。

```text
producer -> queued request -> worker -> run / retry / finish
                  |                         |
              cancel queued              single writer
                  |                         |
                  +------> trace recorder <-+
```
