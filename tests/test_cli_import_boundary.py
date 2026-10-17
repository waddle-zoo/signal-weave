"""Exercise the actual CLI import boundary in fresh Python processes."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("arguments", [["--help"], ["context", "--help"], ["--version"], ["--build-info"]])
def test_lightweight_commands_do_not_load_server_or_decision_dependencies(arguments, tmp_path):
    program = r'''
import importlib.abc
import sys

class RejectRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"signalweave.runtime", "typesafe_sdk", "signalweave.mcp_server"}:
            raise AssertionError("Lightweight CLI loaded a server/decision dependency: " + fullname)

sys.meta_path.insert(0, RejectRuntime())
from signalweave.cli import main
main()
'''
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
    result = subprocess.run([sys.executable, "-c", program, *arguments], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
