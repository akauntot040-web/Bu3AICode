"""ProjectAnalyzerの単体テスト。"""

from __future__ import annotations

from pathlib import Path

from promptagent.analyzer.project_analyzer import ProjectAnalyzer


def test_detects_python_and_markdown_files(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Title\n", encoding="utf-8")
    (tmp_path / "ignored_dir").mkdir()
    (tmp_path / "ignored_dir" / "cache.tmp").write_text("junk", encoding="utf-8")

    analyzer = ProjectAnalyzer()
    analysis = analyzer.analyze(tmp_path)

    languages = {f.language for f in analysis.files}
    assert "Python" in languages
    assert "Markdown" in languages


def test_ignores_configured_patterns(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("module.exports = {}", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")

    analyzer = ProjectAnalyzer(ignore_patterns=["node_modules"])
    analysis = analyzer.analyze(tmp_path)

    paths = [str(f.path) for f in analysis.files]
    assert not any("node_modules" in p for p in paths)
    assert any("app.js" in p for p in paths)


def test_detects_manifest_files(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}', encoding="utf-8")

    analyzer = ProjectAnalyzer()
    analysis = analyzer.analyze(tmp_path)

    assert "Node.js" in analysis.manifests
    assert "react" in analysis.dependencies.get("Node.js", [])
