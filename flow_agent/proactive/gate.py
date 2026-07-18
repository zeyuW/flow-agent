"""主动检查执行前的准入规则。"""

import sqlite3
import threading
import time
from dataclasses import dataclass, field

from pathlib import Path
from flow_agent.proactive.models import GateResult


@dataclass
class ProactiveStateStore:
    """保存最近发送时间、去重键、每日配额和漂移时间。"""

    db_path: str | Path | None = None
    _last_sent: float = 0.0
    _delivery_keys: dict[str, float] = field(default_factory=dict)
    _daily_count: int = 0
    _day_start: float = 0.0
    _drift_last_at: float = 0.0

    def __post_init__(self) -> None:
        """连接可选 SQLite 数据库并恢复上次运行状态。"""

        self._lock = threading.RLock()
        self._db = None
        if self.db_path is None:
            return
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute('PRAGMA journal_mode=WAL')
        self._initialize_schema()
        self._load_persisted_state()


    def _initialize_schema(self) -> None:
        """创建主动状态、交付去重和霍克斯事件表。"""

        if self._db is None:
            return
        with self._lock:
            self._db.execute(
                'CREATE TABLE IF NOT EXISTS proactive_state (id INTEGER PRIMARY KEY CHECK (id = 1), last_sent REAL NOT NULL, daily_count INTEGER NOT NULL, day_start REAL NOT NULL, drift_last_at REAL NOT NULL)'
            )
            self._db.execute(
                'CREATE TABLE IF NOT EXISTS delivery_keys (delivery_key TEXT PRIMARY KEY, delivered_at REAL NOT NULL)'
            )
            self._db.execute(
                'CREATE TABLE IF NOT EXISTS hawkes_events (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL, event_type TEXT NOT NULL, weight REAL NOT NULL)'
            )
            self._db.execute(
                'INSERT OR IGNORE INTO proactive_state (id, last_sent, daily_count, day_start, drift_last_at) VALUES (1, 0, 0, 0, 0)'
            )
            self._db.commit()


    def _load_persisted_state(self) -> None:
        """从数据库恢复配额、冷却、漂移和去重状态。"""

        if self._db is None:
            return
        with self._lock:
            row = self._db.execute(
                'SELECT last_sent, daily_count, day_start, drift_last_at FROM proactive_state WHERE id = 1'
            ).fetchone()
            key_rows = self._db.execute(
                'SELECT delivery_key, delivered_at FROM delivery_keys'
            ).fetchall()
        if row is not None:
            self._last_sent, self._daily_count, self._day_start, self._drift_last_at = row
        self._delivery_keys = {str(key): float(timestamp) for key, timestamp in key_rows}


    def _persist_runtime_state(self) -> None:
        """把当前配额、冷却和漂移状态写入数据库。"""

        if self._db is None:
            return
        with self._lock:
            self._db.execute(
                'UPDATE proactive_state SET last_sent = ?, daily_count = ?, day_start = ?, drift_last_at = ? WHERE id = 1',
                (
                    self._last_sent, self._daily_count, self._day_start, self._drift_last_at,
                ),
            )
            self._db.commit()


    def get_last_sent_at(self) -> float:
        """返回最近一次成功发送时间。"""

        return self._last_sent

    def mark_sent(self, *delivery_keys: str) -> None:
        """把一次成功发送及其全部去重键作为一个配额事件记录。"""

        now = time.time()
        self._last_sent = now
        for delivery_key in delivery_keys:
            if delivery_key:
                self._delivery_keys[delivery_key] = now
        day = int(now // 86400)
        if int(self._day_start // 86400) != day:
            self._daily_count = 0
            self._day_start = now
        self._daily_count += 1
        if self._db is not None:
            with self._lock:
                self._db.executemany(
                    'INSERT OR REPLACE INTO delivery_keys (delivery_key, delivered_at) VALUES (?, ?)',
                    [(key, now) for key in delivery_keys if key],
                )
                self._db.commit()
        self._persist_runtime_state()

    def was_delivered(self, delivery_key: str, window: float = 3600.0) -> bool:
        """检查去重键是否在给定窗口内成功发送过。"""

        if not delivery_key:
            return False
        timestamp = self._delivery_keys.get(delivery_key, 0.0)
        return timestamp > 0 and (time.time() - timestamp) < window

    @property
    def daily_count(self) -> int:
        """返回当前自然日内的成功发送次数。"""

        day = int(time.time() // 86400)
        if int(self._day_start // 86400) != day:
            return 0
        return self._daily_count

    def mark_drift_run(self) -> None:
        """记录最近一次漂移运行时间。"""

        self._drift_last_at = time.time()
        self._persist_runtime_state()

    def get_drift_last_at(self) -> float:
        """返回最近一次漂移运行时间。"""

        return self._drift_last_at

    def append_interaction_event(self, timestamp: float, event_type: str, weight: float) -> None:
        """持久化一条影响霍克斯强度的真实互动事件。"""

        if self._db is None:
            return
        with self._lock:
            self._db.execute(
                'INSERT INTO hawkes_events (timestamp, event_type, weight) VALUES (?, ?, ?)',
                (timestamp, event_type, weight),
            )
            self._db.commit()


    def load_interaction_events(self, since: float) -> list[tuple[float, str, float]]:
        """加载保留窗口内的霍克斯互动事件。"""

        if self._db is None:
            return []
        with self._lock:
            rows = self._db.execute(
                'SELECT timestamp, event_type, weight FROM hawkes_events WHERE timestamp >= ? ORDER BY timestamp',
                (since,),
            ).fetchall()
        return [
            (float(timestamp), str(event_type), float(weight))
            for timestamp, event_type, weight in rows
        ]

    def close(self) -> None:
        """提交并关闭主动状态数据库连接。"""

        if self._db is None:
            return
        with self._lock:
            self._db.close()
            self._db = None


@dataclass(slots=True)
class AnyActionGate:
    """限制每日发送次数和相邻发送的最小间隔。"""

    max_per_day: int = 5
    min_interval: float = 0.0

    def should_act(self, store: ProactiveStateStore, base_score: float) -> bool:
        """判断当前状态是否仍允许尝试主动动作。"""

        if store.daily_count >= self.max_per_day:
            return False
        last_sent = store.get_last_sent_at()
        if last_sent > 0 and (time.time() - last_sent) < self.min_interval:
            return False
        return True


def check_gate(
    *,
    chat_id: str = "",
    is_busy: bool = False,
    state_store: ProactiveStateStore | None = None,
    any_action: AnyActionGate | None = None,
    cooldown: float = 120.0,
    base_score: float = 0.0,
) -> GateResult:
    """依次检查目标、被动链路占用、冷却和每日配额。"""

    if not chat_id:
        return GateResult(passed=False, reason="no_target")
    if is_busy:
        return GateResult(passed=False, reason="passive_busy")

    if state_store is not None:
        last_sent = state_store.get_last_sent_at()
        if last_sent > 0 and (time.time() - last_sent) < cooldown:
            return GateResult(passed=False, reason="cooldown")

    if any_action is not None and state_store is not None:
        if not any_action.should_act(state_store, base_score):
            return GateResult(passed=False, reason="any_action_blocked")

    next_interval = max(30.0, 300.0 - max(0.0, base_score) * 200.0)
    return GateResult(passed=True, reason="ok", next_interval=next_interval)
