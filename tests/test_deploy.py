import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from playwright.sync_api import Error

from app import setup_browser

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fake_service_tools(tmp_path, monkeypatch):
    if os.geteuid() == 0:
        pytest.skip("The rootless installer intentionally refuses a root caller")
    directory = tmp_path / "tools"
    directory.mkdir()
    log = tmp_path / "commands.jsonl"
    program = directory / "fake-tool"
    program.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "name = pathlib.Path(sys.argv[0]).name\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['MATCHDAY_TEST_LOG'], 'a') as output:\n"
        "    output.write(json.dumps([name, *args]) + '\\n')\n"
        "if name == 'podman' and args[0] == 'info':\n"
        "    print(os.environ.get('MATCHDAY_TEST_CGROUP', 'v2'))\n"
        "if name == 'podman' and args[0] == 'build':\n"
        "    sys.exit(int(os.environ.get('MATCHDAY_TEST_BUILD_EXIT', '0')))\n"
    )
    program.chmod(0o755)
    for name in ("podman", "systemctl", "git"):
        (directory / name).symlink_to(program)
    monkeypatch.setenv("PATH", f"{directory}:{os.environ['PATH']}")
    monkeypatch.setenv("MATCHDAY_TEST_LOG", str(log))

    def run(action):
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/server-podman"), action],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        commands = [json.loads(line) for line in log.read_text().splitlines()]
        return result, commands

    return run


def test_podman_build_uses_the_checkout_and_containerfile(fake_service_tools):
    result, commands = fake_service_tools("build")
    assert result.returncode == 0
    assert commands[-1] == [
        "podman",
        "build",
        "--tag",
        "localhost/matchday:latest",
        "--file",
        str(ROOT / "deploy/Containerfile"),
        str(ROOT),
    ]
    assert not any(command[:3] == ["systemctl", "--user", "restart"] for command in commands)


def test_failed_container_update_keeps_existing_service_running(fake_service_tools, monkeypatch):
    monkeypatch.setenv("MATCHDAY_TEST_BUILD_EXIT", "7")
    result, commands = fake_service_tools("update")
    assert result.returncode == 7
    assert ["git", "pull", "--ff-only"] in commands
    assert not any("stop" in command or "restart" in command for command in commands)


def test_container_update_restarts_only_after_the_build(fake_service_tools):
    result, commands = fake_service_tools("update")
    assert result.returncode == 0
    build = next(i for i, command in enumerate(commands) if command[:2] == ["podman", "build"])
    restart = commands.index(["systemctl", "--user", "restart", "matchday.service"])
    assert restart > build
    assert "preserved" in result.stdout


def test_podman_requires_cgroup_v2_before_building(fake_service_tools, monkeypatch):
    monkeypatch.setenv("MATCHDAY_TEST_CGROUP", "v1")
    result, commands = fake_service_tools("build")
    assert result.returncode == 1
    assert "cgroup v2" in result.stderr
    assert not any(command[:2] == ["podman", "build"] for command in commands)


def test_container_restart_targets_user_service(fake_service_tools):
    result, commands = fake_service_tools("restart")
    assert result.returncode == 0
    assert commands == [["systemctl", "--user", "restart", "matchday.service"]]


def test_rhel_browser_failure_points_to_podman_instead_of_apt(monkeypatch):
    commands = []
    monkeypatch.setattr(
        setup_browser.subprocess, "run", lambda command, **kwargs: commands.append(command)
    )
    monkeypatch.setattr(setup_browser.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        setup_browser.platform,
        "freedesktop_os_release",
        lambda: {"ID": "almalinux", "ID_LIKE": "rhel centos fedora"},
    )

    def failed_browser():
        raise Error("Missing browser library")

    monkeypatch.setattr(setup_browser, "check_browser", failed_browser)
    with pytest.raises(SystemExit, match="deploy/almalinux.md"):
        setup_browser.main()
    assert commands == [[sys.executable, "-m", "playwright", "install", "chromium"]]
