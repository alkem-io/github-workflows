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
    offset = start
    for candidate in text[start:].splitlines(keepends=True):
        if candidate.startswith("  ") and not candidate.startswith("    "):
            end = offset
            break
        offset += len(candidate)
    return text[start:end]


def setup_script(block: str) -> str:
    return named_step_script(block, "Run repository setup")


def named_step_script(block: str, name: str) -> str:
    marker = f"      - name: {name}\n"
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


def run_script(
    script: str, repo: Path, extra_env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(extra_env)
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
        hook = repo / "ci" / "setup.sh"
        hook.parent.mkdir()
        hook.write_text("#!/usr/bin/env bash\nprintf ran > setup.marker\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "ci/setup.sh"], check=True)

        assert run_script(scripts[0], repo, {"SETUP_SCRIPT": ""}).returncode == 0
        assert not (repo / "setup.marker").exists()
        assert run_script(scripts[0], repo, {"SETUP_SCRIPT": "ci/setup.sh"}).returncode == 0
        assert (repo / "setup.marker").read_text(encoding="utf-8") == "ran"
        option_named = repo / "-rf.sh"
        option_named.write_text(
            "#!/usr/bin/env bash\nprintf option-safe > option.marker\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(repo), "add", "--", "-rf.sh"], check=True)
        assert run_script(scripts[0], repo, {"SETUP_SCRIPT": "-rf.sh"}).returncode == 0
        assert (repo / "option.marker").read_text(encoding="utf-8") == "option-safe"
        missing = run_script(scripts[0], repo, {"SETUP_SCRIPT": "missing.sh"})
        assert missing.returncode != 0
        assert "setup-script must name a committed regular file" in missing.stdout
        untracked = repo / "untracked.sh"
        untracked.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        assert run_script(scripts[0], repo, {"SETUP_SCRIPT": "untracked.sh"}).returncode != 0

        absolute = run_script(scripts[0], repo, {"SETUP_SCRIPT": str(hook.resolve())})
        assert absolute.returncode != 0
        assert "setup-script must be a repo-relative path" in absolute.stdout
        traversal = run_script(scripts[0], repo, {"SETUP_SCRIPT": "ci/../ci/setup.sh"})
        assert traversal.returncode != 0
        assert "setup-script must be a repo-relative path" in traversal.stdout

        outside = repo.parent / "outside.sh"
        outside.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        symlink = repo / "ci" / "outside.sh"
        symlink.symlink_to(outside)
        subprocess.run(["git", "-C", str(repo), "add", "ci/outside.sh"], check=True)
        linked = run_script(scripts[0], repo, {"SETUP_SCRIPT": "ci/outside.sh"})
        assert linked.returncode != 0
        assert "setup-script must name a committed regular file" in linked.stdout

        fake_bin = repo / "bin"
        fake_bin.mkdir()
        fake_go = fake_bin / "go"
        fake_go.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$FAKE_TOTAL\"\n", encoding="utf-8")
        fake_go.chmod(0o755)
        summary = repo / "summary.md"
        coverage_script = named_step_script(job_block(text, "test-unit"), "Coverage summary")
        coverage_env = {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "GITHUB_STEP_SUMMARY": str(summary),
            "COVERAGE_MIN": "95",
            "FAKE_TOTAL": "total: (statements) 96.0%",
        }
        assert run_script(coverage_script, repo, coverage_env).returncode == 0
        coverage_env["FAKE_TOTAL"] = "total: (statements) 94.0%"
        assert run_script(coverage_script, repo, coverage_env).returncode != 0
        coverage_env["FAKE_TOTAL"] = "total: (statements) no test files"
        malformed = run_script(coverage_script, repo, coverage_env)
        assert malformed.returncode != 0
        assert "could not parse total coverage" in malformed.stdout
        coverage_env["FAKE_TOTAL"] = "total: (statements) 96.0%"
        coverage_env["COVERAGE_MIN"] = ""
        assert run_script(coverage_script, repo, coverage_env).returncode != 0

    unit_block = job_block(text, "test-unit")
    assert "COVERAGE_MIN: ${{ inputs.coverage-min }}" in unit_block
    assert "inputs.coverage-min > 0 && !inputs.coverage" in unit_block
    print("go-ci reusable-workflow contract: ok")


if __name__ == "__main__":
    main()
