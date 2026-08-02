from pathlib import Path

from .import_graph import build_import_graph, find_import_cycles


def write_module(source: Path, name: str, content: str) -> None:
    path = source.joinpath(*name.split(".")).with_suffix(".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_import_graph_finds_cycle(tmp_path: Path):
    source = tmp_path / "src"
    write_module(source, "sample.__init__", "")
    write_module(source, "sample.a", "from sample.b import value\n")
    write_module(source, "sample.b", "from sample.a import value\n")

    graph = build_import_graph(source, {"sample"})

    assert find_import_cycles(graph) == [("sample.a", "sample.b")]


def test_import_graph_resolves_relative_import_and_ignores_external(tmp_path: Path):
    source = tmp_path / "src"
    write_module(source, "sample.__init__", "")
    write_module(source, "sample.a", "from . import b\nimport pathlib\n")
    write_module(source, "sample.b", "value = 1\n")

    graph = build_import_graph(source, {"sample"})

    assert graph["sample.a"] == {"sample.b"}
    assert find_import_cycles(graph) == []
