# Design

`PluginManager` 的贡献变更回调由应用装配层统一处理：保留 MCP 注册刷新，同时把新的主动数据源和模块快照提交给 `ProactiveLoop.request_contributions_refresh()`。

主动循环在自己的 asyncio 事件循环中创建刷新任务。刷新先编译候选生命周期图并启动候选轮询模块；候选失败时释放候选资源并保留旧对象。候选成功后，在刷新锁内替换管道贡献，停止旧扩展和轮询任务，再发布候选对象。单次 tick 同样使用刷新锁，保证不会读取半代贡献。

```text
plugin watcher thread
        | call_soon_threadsafe
        v
proactive asyncio loop
        | compile -> prepare -> swap
        v
pipeline sources + lifecycle + polling tasks
```
