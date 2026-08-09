# Design

标准化条目保存稳定 `source_key`。解析阶段按来源分组被引用事件，投递成功后的副作用仅调用该来源的 `ack_tool`。
