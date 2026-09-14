"""deploy/termux/run-bot.sh must refuse to start a second bot.

Telegram allows one polling process per token; a second one gets 409 Conflict
forever (which is exactly what happened in practice). The supervisor keeps a
pid file so the second launch fails loudly instead of fighting the first.
"""

import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "deploy" / "termux" / "run-bot.sh"


@pytest.fixture
def project(tmp_path):
    """A throwaway copy of the script in its own project tree, so the guard
    writes its pid file there and never touches the real state/ dir."""
    target = tmp_path / "deploy" / "termux"
    target.mkdir(parents=True)
    shutil.copy(SCRIPT, target / "run-bot.sh")
    return tmp_path


def _run(project):
    return subprocess.run(
        ["bash", str(project / "deploy" / "termux" / "run-bot.sh")],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_refuses_to_start_when_another_instance_holds_the_pid_file(project):
    other = subprocess.Popen(["sleep", "30"])
    try:
        pid_file = project / "state" / "bot.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(f"{other.pid}\n")

        result = _run(project)

        assert result.returncode == 2
        assert "already running" in result.stdout
        assert "409" in result.stdout
        assert str(other.pid) in result.stdout  # tells you what to kill
        assert pid_file.read_text().strip() == str(other.pid), (
            "the refusing instance must not clear the running instance's claim"
        )
    finally:
        other.terminate()
        other.wait(timeout=5)


def test_stale_pid_file_does_not_block_a_restart(project):
    """An Android kill leaves the pid file behind — that must not wedge it."""
    dead = subprocess.Popen(["true"])
    dead.wait(timeout=5)
    time.sleep(0.1)

    pid_file = project / "state" / "bot.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{dead.pid}\n")

    result = _run(project)

    assert "stale pid file" in result.stdout.lower()
    assert "already running" not in result.stdout
    # Gets past the guard and stops on the next precondition instead.
    assert result.returncode == 1
    assert "No virtualenv found" in result.stdout


def test_empty_pid_file_is_treated_as_stale(project):
    pid_file = project / "state" / "bot.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("")

    result = _run(project)

    assert result.returncode == 1
    assert "already running" not in result.stdout


def test_pid_file_is_removed_on_exit(project):
    """Otherwise every clean shutdown would leave a stale file behind."""
    result = _run(project)

    assert result.returncode == 1  # no venv
    assert not (project / "state" / "bot.pid").exists()
