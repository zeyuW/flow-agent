"""普通 Skill 的多来源只读目录。"""

from pathlib import Path

from application.capabilities.skills.loader import SkillLoader
from application.capabilities.skills.models import SkillCatalogItem, SkillSource


class SkillCatalog:
    """扫描内置、项目与本机已安装 Skill，并标记重名冲突。"""

    def __init__(
        self,
        builtin_dir: Path,
        project_dir: Path,
        installed_dir: Path,
    ) -> None:
        self._directories: tuple[tuple[SkillSource, Path], ...] = (
            ("builtin", builtin_dir),
            ("project", project_dir),
            ("installed", installed_dir),
        )

    def list_items(self, *, include_builtin: bool = False) -> list[SkillCatalogItem]:
        items = [
            SkillCatalogItem(spec=spec, source=source)
            for source, directory in self._directories
            for spec in SkillLoader(directory).load()
        ]
        self._mark_conflicts(items)
        if not include_builtin:
            items = [item for item in items if item.source != "builtin"]
        return sorted(items, key=lambda item: (item.name, item.source))

    @staticmethod
    def _mark_conflicts(items: list[SkillCatalogItem]) -> None:
        by_name: dict[str, list[SkillCatalogItem]] = {}
        for item in items:
            by_name.setdefault(item.name, []).append(item)
        for same_name_items in by_name.values():
            if len(same_name_items) < 2:
                continue
            for item in same_name_items:
                item.status = "conflict"
                item.reason = "同名 Skill 冲突"
