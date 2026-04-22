import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from xml.etree import ElementTree

from flow_agent.memory.store import MessageStore
from flow_agent.proactive.types import ProactiveCandidate, SourceRecord


logger = logging.getLogger(__name__)


class ProactiveSource(Protocol):
    """Common source contract for proactive candidate generation."""

    @property
    def name(self) -> str:
        ...

    def fetch_records(self) -> list[SourceRecord]:
        ...


def record_to_candidate(record: SourceRecord) -> ProactiveCandidate:
    """Convert normalized source record into proactive candidate."""

    rendered = record.summary.strip() or record.content.strip()
    content = f"[{record.source}] {record.title}: {rendered}"
    return ProactiveCandidate(
        key=record.dedup_key,
        content=content,
        source=record.source,
        priority=record.priority_hint,
    )


class LocalFileSource:
    '''从本地文件中加载文本候选行'''

    def __init__(self, source_file: Path) -> None:
        self.source_file = source_file

    @property
    def name(self) -> str:
        return "file_feed"

    def fetch_records(self) -> list[SourceRecord]:
        if not self.source_file.exists():
            return []
        records: list[SourceRecord] = []
        for line in self.source_file.read_text(encoding="utf-8").splitlines():
            content = line.strip()
            if not content or content.startswith("#"):
                continue
            records.append(
                SourceRecord(
                    source=self.name,
                    title=content[:48] if len(content) > 48 else content,
                    content=content,
                    summary=content[:120],
                    dedup_key=f"{self.name}:{content.lower()}",
                    priority_hint=0.4,
                )
            )
        return records


class LocalTodoSource:
    '''从本地TODO文件中加载TODO项'''

    def __init__(self, todo_file: Path) -> None:
        self.todo_file = todo_file

    @property
    def name(self) -> str:
        return "local_todo"

    def fetch_records(self) -> list[SourceRecord]:
        if not self.todo_file.exists():
            return []
        records: list[SourceRecord] = []
        for line in self.todo_file.read_text(encoding="utf-8").splitlines():
            content = line.strip()
            if not content or content.startswith("#"):
                continue
            records.append(
                SourceRecord(
                    source=self.name,
                    title=content[:48] if len(content) > 48 else content,
                    content=f"[TODO] {content}",
                    summary=content[:120],
                    dedup_key=f"todo:{content.lower()}",
                    priority_hint=0.9,
                )
            )
        return records


class MemoryFollowUpSource:
    '''从最近的用户问题中构建跟进记录'''

    def __init__(self, store: MessageStore, session_id: str = "default") -> None:
        self.store = store
        self.session_id = session_id

    @property
    def name(self) -> str:
        return "memory_followup"

    def fetch_records(self) -> list[SourceRecord]:
        history = self.store.list_messages(self.session_id)
        for msg in reversed(history[-10:]):
            if msg.get("role") != "user":
                continue
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            if "?" in content or "？" in content:
                return [
                    SourceRecord(
                        source=self.name,
                        title="Follow-up question",
                        content=f"你之前问过：{content}",
                        summary=content[:120],
                        dedup_key=f"{self.name}:{content.lower()}",
                        priority_hint=0.7,
                    )
                ]
        return []


class RSSFeedSource:
    '''从本地文件中读取RSS XML feeds'''

    def __init__(self, feed_files: list[Path]) -> None:
        self.feed_files = feed_files

    @property
    def name(self) -> str:
        return "rss_feed"

    def fetch_records(self) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        for feed_file in self.feed_files:
            if not feed_file.exists():
                continue
            try:
                root = ElementTree.fromstring(feed_file.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("failed to parse rss feed: %s", feed_file)
                continue
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "untitled").strip()
                link = (item.findtext("link") or "").strip()
                description = (item.findtext("description") or "").strip()
                host = urlparse(link).netloc or feed_file.name
                content = description or title
                records.append(
                    SourceRecord(
                        source=self.name,
                        title=title,
                        content=content,
                        summary=content[:160],
                        dedup_key=f"rss:{host}:{title.lower()}",
                        priority_hint=0.5,
                        fetched_at=datetime.now(tz=timezone.utc),
                    )
                )
        return records


class WebSnapshotSource:
    '''从本地文本文件中加载抓取的网页快照'''

    def __init__(self, snapshot_files: list[Path]) -> None:
        self.snapshot_files = snapshot_files

    @property
    def name(self) -> str:
        return "web_fetch"

    def fetch_records(self) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        for snapshot in self.snapshot_files:
            if not snapshot.exists():
                continue
            try:
                text = snapshot.read_text(encoding="utf-8").strip()
            except Exception:
                logger.exception("failed reading web snapshot: %s", snapshot)
                continue
            if not text:
                continue
            records.append(
                SourceRecord(
                    source=self.name,
                    title=snapshot.stem,
                    content=text,
                    summary=text[:160],
                    dedup_key=f"web:{snapshot.name}:{hash(text)}",
                    priority_hint=0.45,
                    fetched_at=datetime.now(tz=timezone.utc),
                )
            )
        return records

