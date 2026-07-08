"""プロジェクト解析エンジン。

起動時にプロジェクトルート配下を走査し、使用言語・依存関係・ファイル構成を
検出する。結果は `context.cache` によりSQLiteキャッシュされ、次回起動を
高速化する。
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path

_EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".sh": "Shell",
    ".sql": "SQL",
    ".toml": "TOML",
}

_MANIFEST_FILES: dict[str, str] = {
    "pyproject.toml": "Python (pyproject)",
    "requirements.txt": "Python (pip)",
    "package.json": "Node.js",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java (Maven)",
    "build.gradle": "Java (Gradle)",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
}


@dataclass(slots=True)
class FileInfo:
    """個々のファイルに関する解析結果。"""

    path: Path
    language: str
    size_bytes: int


@dataclass(slots=True)
class ProjectAnalysis:
    """プロジェクト全体の解析結果。"""

    root: Path
    files: list[FileInfo] = field(default_factory=list)
    language_counts: dict[str, int] = field(default_factory=dict)
    manifests: list[str] = field(default_factory=list)
    is_git_repo: bool = False
    dependencies: dict[str, list[str]] = field(default_factory=dict)

    def summary_line(self) -> str:
        """ステータスバー等に表示する短い言語サマリを返す。"""
        if not self.language_counts:
            return "unknown"
        top = sorted(self.language_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
        return ", ".join(f"{name}({count})" for name, count in top)

    def to_dict(self) -> dict:
        """キャッシュ保存用の辞書表現を返す。"""
        return {
            "root": str(self.root),
            "files": [
                {"path": str(f.path), "language": f.language, "size_bytes": f.size_bytes}
                for f in self.files
            ],
            "language_counts": self.language_counts,
            "manifests": self.manifests,
            "is_git_repo": self.is_git_repo,
            "dependencies": self.dependencies,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectAnalysis":
        """キャッシュされた辞書から復元する。"""
        return cls(
            root=Path(data["root"]),
            files=[
                FileInfo(path=Path(f["path"]), language=f["language"], size_bytes=f["size_bytes"])
                for f in data["files"]
            ],
            language_counts=data["language_counts"],
            manifests=data["manifests"],
            is_git_repo=data["is_git_repo"],
            dependencies=data.get("dependencies", {}),
        )


class ProjectAnalyzer:
    """プロジェクトルートを走査し `ProjectAnalysis` を生成するクラス。"""

    def __init__(self, ignore_patterns: list[str] | None = None, max_file_size_kb: int = 512) -> None:
        self._ignore_patterns = ignore_patterns or []
        self._max_file_size_bytes = max_file_size_kb * 1024

    def analyze(self, root: Path) -> ProjectAnalysis:
        """プロジェクトルートを再帰的に走査して解析結果を返す。"""
        root = root.resolve()
        analysis = ProjectAnalysis(root=root, is_git_repo=(root / ".git").exists())

        for path in self._iter_files(root):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > self._max_file_size_bytes:
                continue
            language = _EXTENSION_LANGUAGE_MAP.get(path.suffix.lower(), "")
            if not language:
                continue
            analysis.files.append(FileInfo(path=path, language=language, size_bytes=size))
            analysis.language_counts[language] = analysis.language_counts.get(language, 0) + 1

        for manifest_name, manifest_label in _MANIFEST_FILES.items():
            manifest_path = root / manifest_name
            if manifest_path.exists():
                analysis.manifests.append(manifest_label)
                analysis.dependencies[manifest_label] = self._parse_dependencies(manifest_path)

        return analysis

    def _iter_files(self, root: Path):
        """無視パターンを考慮しつつファイルを再帰的に列挙する。"""
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if self._is_ignored(relative):
                continue
            yield path

    def _is_ignored(self, relative: Path) -> bool:
        """相対パスが無視パターンに一致するか判定する。"""
        parts = relative.parts
        for pattern in self._ignore_patterns:
            if any(fnmatch.fnmatch(part, pattern) for part in parts):
                return True
            if fnmatch.fnmatch(relative.as_posix(), pattern):
                return True
        return False

    def _parse_dependencies(self, manifest_path: Path) -> list[str]:
        """マニフェストファイルから依存パッケージ名の一覧を抽出する。"""
        try:
            if manifest_path.name == "package.json":
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                deps = list(data.get("dependencies", {}).keys())
                deps += list(data.get("devDependencies", {}).keys())
                return deps
            if manifest_path.name == "requirements.txt":
                lines = manifest_path.read_text(encoding="utf-8").splitlines()
                return [line.split("==")[0].split(">=")[0].strip() for line in lines if line.strip() and not line.startswith("#")]
            if manifest_path.name == "pyproject.toml":
                import tomllib

                data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
                deps = data.get("project", {}).get("dependencies", [])
                return [str(d) for d in deps]
        except Exception:
            return []
        return []
