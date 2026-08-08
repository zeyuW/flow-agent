import ast
from pathlib import Path


def test_main_entrypoint_calls_main_after_definition():
    repository_root = Path(__file__).parents[2]
    source_path = repository_root / "src" / "bootstrap" / "main.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))

    main_index = next(
        index
        for index, node in enumerate(module.body)
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    entrypoint_index = next(
        index
        for index, node in enumerate(module.body)
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        )
    )

    assert entrypoint_index > main_index


def test_service_app_owns_lifecycle_methods():
    repository_root = Path(__file__).parents[2]
    source_path = repository_root / "src" / "bootstrap" / "service_app.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))

    service_app = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "ServiceApp"
    )
    methods = {
        node.name
        for node in service_app.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert {"init", "start", "wait", "stop"} <= methods
