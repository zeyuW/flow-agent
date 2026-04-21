from pathlib import Path


class LocalDriftRunner:
    def __init__(self, tasks_file: Path) -> None:
        self.tasks_file = tasks_file

    def run(self) -> str:
        if not self.tasks_file.exists():
            return "no_task"
        for line in self.tasks_file.read_text(encoding="utf-8").splitlines():
            task = line.strip()
            if task and not task.startswith("#"):
                # stage10最小版：只做“选中轻任务”并记录，不执行复杂动作
                return f"selected:{task}"
        return "no_task"
