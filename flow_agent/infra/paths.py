from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / ".flow_agent"


def get_memory_db_path() -> Path:
    return DATA_DIR / "memory.db"
