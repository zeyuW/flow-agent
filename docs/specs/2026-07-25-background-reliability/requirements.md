# Requirements

## Goal

后台任务在失败时按错误类别安全重试，并将提交、开始、重试、完成和取消写入结构化观测记录。

## Functional requirements

- `JobSpec` 支持重试延迟和退避倍率；未显式配置时保持当前零延迟重试兼容行为。
- 仅可重试的错误进入下一次尝试；永久错误和未知错误立即失败，不消耗剩余重试次数。
- `BackgroundRuntime.cancel_queued_job(job_name)` 只能取消尚未开始执行的任务，并返回实际取消数量。
- 已开始的同步任务不可被强制终止；取消请求不得伪造其已停止或解除同任务合并保护。
- 运行时可选接收 `TraceRecorder`，按 `background_job_queued`、`background_job_started`、`background_job_retrying`、`background_job_finished` 和 `background_job_cancelled` 记录结构化事件；未配置 recorder 时保持无副作用。
- 每个运行事件包含任务名、运行 ID（已创建时）、尝试次数、状态与错误类别；不得写入任务结果的完整内容。

## Non-goals

- 不强制中断正在运行的同步函数，也不宣称实现硬超时。
- 不引入跨进程取消、持久化取消命令或分布式 lease。
- 不改变用户级定时提醒的存储和投递模型。
