# Design

## Data flow

```text
工具调用 / EventBus / interval loop
              |
              v
       有界 FIFO 执行队列
              |
              v
       N 个后台任务 worker
              |
              v
       单一 SQLite writer
```

`JobSpec` 增加可选触发和调度字段。运行时启动时订阅事件总线并启动间隔线程；停止时先撤销触发器，再停止 worker，最后关闭 writer 和存储。

队列 admission 在同一锁中检查容量及 `queued_or_running` 任务键。默认合并可避免同一任务的重复副作用；关闭合并的任务仍可并发执行。成功任务记录最近成功时间，防抖仅据此判断。

worker 从 FIFO 队列取出任务并复用现有 `run_job` 的状态、重试和写入流程。所有 store 写操作继续使用 `JobStoreWriter`，读取保持直接读取。
