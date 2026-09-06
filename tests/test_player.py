"""Exercise player recovery with the Node runtime already shipped by Playwright."""

import subprocess
from pathlib import Path

import playwright


def test_player_recovery():
    node = Path(playwright.__file__).parent / "driver" / "node"
    if not node.exists():
        node = node.with_suffix(".exe")
    subprocess.run(
        [str(node), "--test", str(Path(__file__).with_name("player.test.cjs"))],
        check=True,
        timeout=15,
    )
