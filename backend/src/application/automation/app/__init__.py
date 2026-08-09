"""系统和插件自动化作业应用服务。"""

from application.automation.app.runtime import AutomationRegistry, AutomationRuntime
from application.automation.app.executor import AutomationExecutor

__all__ = [
    "AutomationRegistry",
    "AutomationRuntime",
    "AutomationExecutor",
]
