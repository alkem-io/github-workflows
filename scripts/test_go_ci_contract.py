#!/usr/bin/env python3
"""Structural and behavioral contract test for the reusable Go workflow."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "go-ci.yml"
COMPILE_JOBS = ("lint", "test-unit", "build", "test-extra", "openapi")


def job_block(text: str, name: str) -> str:
    marker = f"  {name}:\n"
    start = text.index(marker) + len(marker)
    end = len(text)
    for candidate in text[start:].splitlines(keepends=True):
        if candidate.startswith("  ") and not candidate.startswith("    "):
            end = start + text[start:].index(candidate)
            break
    return text[start:end]


def setup_script(block: str) -> str:
    marker = "      - name: Run repository setup\n"
    start = block.index(marker) + len(marker)
    step = block[start:]
    run_marker = "        run: |\n"
    run_start = step.index(run_marker) + len(run_marker)
    lines: list[str] = []
    for line in step[run_start:].splitlines():
        if line and not line.startswith("          "):
            break
        lines.append(line[10:] if line else "")
    return "\n".join(lines) + "\n"


def run_setup(script: str, repo: Path, setup_path: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SETUP_SCRIPT"] = setup_path
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "      setup-script:\n" in text
    assert "      coverage-min:\n" in text

    scripts = []
    for job in COMPILE_JOBS:
        block = job_block(text, job)
        assert "SETUP_SCRIPT: ${{ inputs.setup-script }}" in block, job
        scripts.append(setup_script(block))
    assert len(set(scripts)) == 1, "setup behavior drifted between compile jobs"

    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        hook = repo / "setup.sh"
        hook.write_text("#!/usr/bin/env bash\nprintf ran > setup.marker\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "setup.sh"], check=True)

        assert run_setup(scripts[0], repo, "").returncode == 0
        assert not (repo / "setup.marker").exists()
        assert run_setup(scripts[0], repo, "setup.sh").returncode == 0
        assert (repo / "setup.marker").read_text(encoding="utf-8") == "ran"
        assert run_setup(scripts[0], repo, "missing.sh").returncode != 0
        untracked = repo / "untracked.sh"
        untracked.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        assert run_setup(scripts[0], repo, "untracked.sh").returncode != 0
        assert run_setup(scripts[0], repo, "/tmp/untrusted.sh").returncode != 0

    assert "COVERAGE_MIN: ${{ inputs.coverage-min }}" in job_block(text, "test-unit")
    assert "coverage below configured minimum" in job_block(text, "test-unit")
    print("go-ci reusable-workflow contract: ok")


if __name__ == "__main__":
    main()
