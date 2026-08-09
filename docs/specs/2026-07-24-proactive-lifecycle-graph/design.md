# Design

模块声明 `slot`、`requires`、`produces`、异步 `run` 与可选 `start`/`stop`。编译期拒绝重复生产者、缺失依赖和循环；每轮使用共享槽上下文执行扩展模块。
