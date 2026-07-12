"""Proactive source specifications for plugin integration (参考 akashic-agent)."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class ProactiveSourceSpec(Protocol):
    """主动推送数据源规范（参考 akashic-agent ProactiveSourceSpec）。
    
    插件通过 proactive_sources() 方法返回此规范，声明数据源配置。
    """
    
    @property
    def id(self) -> str:
        """数据源唯一标识符"""
        ...
    
    @property
    def channels(self) -> tuple[str, ...]:
        """支持的通道：alert, content, context"""
        ...
    
    @property
    def server(self) -> str:
        """MCP server 名称"""
        ...
    
    @property
    def fetch_tool(self) -> str:
        """获取数据的工具名称"""
        ...
    
    @property
    def ack_tool(self) -> str | None:
        """确认工具名称（可选）"""
        ...
    
    @property
    def poll_tool(self) -> str | None:
        """轮询工具名称（可选）"""
        ...
    
    @property
    def poll_interval_seconds(self) -> int:
        """轮询间隔（秒）"""
        ...


@dataclass
class ProactiveSourceSpecImpl:
    """ProactiveSourceSpec 的具体实现"""
    id: str
    channels: tuple[str, ...]
    server: str
    fetch_tool: str
    ack_tool: str | None = None
    poll_tool: str | None = None
    poll_interval_seconds: int = 300
    
    def __post_init__(self):
        """验证配置"""
        valid_channels = {"alert", "content", "context"}
        if not all(ch in valid_channels for ch in self.channels):
            raise ValueError(f"Invalid channels: {self.channels}. Must be subset of {valid_channels}")
        
        if not self.id:
            raise ValueError("id cannot be empty")
        
        if not self.server:
            raise ValueError("server cannot be empty")
        
        if not self.fetch_tool:
            raise ValueError("fetch_tool cannot be empty")
        
        if self.poll_interval_seconds < 1:
            raise ValueError("poll_interval_seconds must be >= 1")


@dataclass
class RegisteredProactiveSource:
    """已注册的主动推送数据源"""
    spec: ProactiveSourceSpec
    plugin_id: str
    
    @property
    def source_key(self) -> str:
        """数据源的稳定身份：plugin_id:source_id"""
        return f"{self.plugin_id}:{self.spec.id}"
