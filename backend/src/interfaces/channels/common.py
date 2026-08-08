"""通用基础组件：跨渠道共享的基础设施。"""

import hashlib
from pathlib import Path
from typing import Dict
from infra.lifecycle.paths import WORKSPACE_LAYOUT


class AttachmentStore:
    """附件存储：统一的文件存储管理"""

    def __init__(self, base_path: str | None = None):
        self.base_path = Path(base_path) if base_path else WORKSPACE_LAYOUT.inbound_attachments_dir
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def store(self, file_data: bytes, filename: str, channel: str) -> str:
        """存储文件，返回文件路径"""
        channel_dir = self.base_path / channel
        channel_dir.mkdir(exist_ok=True)
        file_path = channel_dir / filename
        file_path.write_bytes(file_data)
        return str(file_path)

    async def retrieve(self, file_path: str) -> bytes | None:
        """检索文件内容"""
        path = Path(file_path)
        if path.exists():
            return path.read_bytes()
        return None


class SessionIdentityIndex:
    """身份索引：维护用户身份到会话 ID 的映射"""

    def __init__(self):
        self._identity_to_chat_id: Dict[str, str] = {}

    def add_mapping(self, identity: str, chat_id: str) -> None:
        """添加身份映射"""
        self._identity_to_chat_id[identity] = chat_id

    def get_chat_id(self, identity: str) -> str | None:
        """根据身份获取会话 ID"""
        return self._identity_to_chat_id.get(identity)


class MessageDeduper:
    """消息去重：防止重复处理相同的消息"""

    def __init__(self):
        self._processed_hashes: set[str] = set()

    def is_duplicate(self, message_id: str) -> bool:
        """检查消息是否重复"""
        return message_id in self._processed_hashes

    def mark_processed(self, message_id: str) -> None:
        """标记消息已处理"""
        self._processed_hashes.add(message_id)

    @staticmethod
    def compute_hash(content: str) -> str:
        """计算消息内容的哈希值"""
        return hashlib.md5(content.encode()).hexdigest()
