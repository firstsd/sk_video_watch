"""Exercise the Mac installer in an isolated home directory with a stand-in for launchctl."""

import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_launch_agent_install_settings_and_lifecycle(tmp_path, monkeypatch):
    if os.geteuid() == 0:
        pytest.skip("The installer requires an unprivileged user")
    user_dir = tmp_path / "Mac User"
    project = user_dir / "Apps & Games" / "matchday"
    script = project / "scripts/server-macos"
    sample = Path("deploy/matchday-macos.env.example")
    for relative in (Path("scripts/server-macos"), sample):
        (project / relative).parent.mkdir(parents=True)
        shutil.copy2(ROOT / relative, project / relative)

    def executable(path, body):
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    tools = tmp_path / "tools"
    tools.mkdir()
    executable(tools / "uname", "echo Darwin")
    executable(tools / "uv", 'exit "${TEST_SYNC_EXIT:-0}"')
    executable(tools / "git", "exit 0")
    executable(
        tools / "launchctl",
        """case "$1" in
  print) case "$2" in */local.matchday) test -e "$HOME/loaded" ;; *) exit 0 ;; esac ;;
  bootstrap) test -f "$3" && test ! -e "$HOME/disabled" && touch "$HOME/loaded" ;;
  bootout) rm "$HOME/loaded" ;;
  disable) touch "$HOME/disabled" ;;
  enable) rm -f "$HOME/disabled" ;;
  kickstart) test -e "$HOME/loaded" ;;
  *) exit 2 ;;
esac
""",
    )
    monkeypatch.setenv("HOME", str(user_dir))
    monkeypatch.setenv("PATH", f"{tools}:{os.environ['PATH']}")
    python = project / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    executable(
        python,
        'if [ "$1" = -m ] && [ "$2" = app.setup_browser ]; then exit 0; fi\n'
        f'exec {shlex.quote(sys.executable)} "$@"\n',
    )
    (project / "uvicorn.py").write_text(
        "import json, os, sys\nprint(json.dumps([sys.argv[1:], os.environ['MATCHDAY_PASSWORD']]))\n"
    )

    def run(action, *, check=True):
        return subprocess.run([script, action], check=check, capture_output=True, text=True)

    run("install")
    plist = user_dir / "Library/LaunchAgents/local.matchday.plist"
    job = plistlib.loads(plist.read_bytes())
    assert job["WorkingDirectory"] == str(project)
    assert job["RunAtLoad"] and (user_dir / "loaded").exists()
    assert Path(job["StandardErrorPath"]).is_file()
    settings = user_dir / "Library/Application Support/Matchday/matchday.env"
    assert settings.stat().st_mode & 0o777 == 0o600
    assert settings.read_bytes() == (project / sample).read_bytes()

    password = "literal $(exit 99) #=' & $HOME"
    custom = f"MATCHDAY_PORT=8123\nMATCHDAY_AUTH_ENABLED=true\nMATCHDAY_PASSWORD={password}"
    settings.write_text(custom)
    run("install")
    process = subprocess.run(
        job["ProgramArguments"],
        cwd=job["WorkingDirectory"],
        check=True,
        capture_output=True,
        text=True,
    )
    arguments, actual_password = json.loads(process.stdout)
    assert arguments[arguments.index("--port") + 1] == "8123"
    assert actual_password == password
    assert password.encode() not in plist.read_bytes()

    monkeypatch.setenv("TEST_SYNC_EXIT", "42")
    assert run("update", check=False).returncode == 42
    assert (user_dir / "loaded").exists()
    monkeypatch.delenv("TEST_SYNC_EXIT")
    run("stop")
    run("update")
    assert not (user_dir / "loaded").exists() and (user_dir / "disabled").exists()
    run("start")
    run("restart")
    assert (user_dir / "loaded").exists() and not (user_dir / "disabled").exists()
    run("uninstall")
    assert not plist.exists() and not (user_dir / "loaded").exists()
    assert settings.read_text() == custom
