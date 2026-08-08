"""公共基础设施包布局约束。"""

from pathlib import Path


BACKEND_ROOT = Path(__file__).parents[2]
INFRA_ROOT = BACKEND_ROOT / "src" / "infra"


def test_shared_infrastructure_is_grouped_by_cohesive_capability():
    """公共基础设施按能力聚合，不保留过细的技术目录。"""

    expected_modules = {
        "config.py",
        "persistence.py",
        "resilience.py",
        "security.py",
        "telemetry.py",
        "worker.py",
        "runtime.py",
        "workspace.py",
    }
    assert expected_modules <= {
        path.name for path in INFRA_ROOT.glob("*.py")
    }

    removed_directories = {
        "config",
        "persistence",
        "resilience",
        "security",
        "telemetry",
        "worker",
        "lifecycle",
    }
    assert all(not (INFRA_ROOT / name).exists() for name in removed_directories)


def test_infrastructure_container_is_not_a_second_composition_root():
    """应用组装只由 bootstrap 负责，infra 不保留重复容器。"""

    assert not (INFRA_ROOT / "container.py").exists()
