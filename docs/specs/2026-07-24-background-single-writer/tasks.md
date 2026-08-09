# Tasks

- [x] 定义持久化命令与单 writer 生命周期。
- [x] 将运行状态写入迁移到 writer。
- [x] 为 `JobSpec` 增加事件、间隔、合并和防抖声明。
- [x] 将异步提交改为有界 FIFO 队列和固定 worker，并保持手动执行兼容。
- [x] 接入 EventBus 与 interval loop，并处理运行时关闭。
- [x] 增加事件触发、间隔触发、合并、防抖、worker 上限和关闭恢复测试。
