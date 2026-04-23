from __future__ import annotations

from dataclasses import dataclass, field

from flow_agent.registry.base import RegistryItem


@dataclass(slots=True)
class RegistryCatalog:
    """Unified register/list/enable/disable catalog."""

    _items: dict[str, RegistryItem] = field(default_factory=dict)

    def register(self, item: RegistryItem) -> None:
        self._items[item.name] = item

    def list(self) -> list[RegistryItem]:
        return list(self._items.values())

    def enable(self, name: str) -> None:
        self._get(name).enabled = True

    def disable(self, name: str) -> None:
        self._get(name).enabled = False

    def set_health(self, name: str, health: str) -> None:
        self._get(name).health = health

    def metadata(self, name: str) -> dict[str, object]:
        return self._get(name).metadata

    def _get(self, name: str) -> RegistryItem:
        item = self._items.get(name)
        if item is None:
            raise ValueError(f"unknown registry item: {name}")
        return item
