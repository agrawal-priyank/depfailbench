from __future__ import annotations

import hashlib
from pathlib import Path

from benchmark.paths import resolve_data_path


def compose_prompt(
    task: str,
    condition: str,
    root: Path = Path("prompts"),
    scaffolds_root: Path = Path("scaffolds"),
) -> str:
    root = resolve_data_path(root)
    scaffolds_root = resolve_data_path(scaffolds_root)
    shared = (root / "shared_rules.md").read_text().strip()
    task_prompt = (root / f"{task}_{condition}.md").read_text().strip()
    scaffold = (scaffolds_root / task / "app.py").read_text().strip()
    return (
        f"{shared}\n\n{task_prompt}\n\n"
        "# Starting `app.py`\n\n"
        "Replace the complete file below while preserving its public factory signature.\n\n"
        f"```python\n{scaffold}\n```\n"
    )


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()
