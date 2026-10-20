import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from signalweave import local_setup, managed_install, uninstall


def _add_runtime(runtime_root: Path, name: str) -> Path:
    runtime = runtime_root / name
    runtime.mkdir(parents=True)
    (runtime / managed_install.MANAGED_MARKER_NAME).write_bytes(
        managed_install.MANAGED_MARKER_CONTENT
    )
    binary = runtime / "signalweave"
    binary.write_bytes(b"native runtime")
    binary.chmod(0o755)
    return runtime


@pytest.fixture
def managed_install_fixture(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.delenv("SIGNALWEAVE_HOME", raising=False)
    key = tmp_path / "external-key"
    key.write_text("private-test-key")
    key.chmod(0o600)
    home = local_setup.initialize(key_file=key)
    (home / "state" / "cards.json").write_text('{"preserve": true}')

    bin_directory = user / ".local" / "bin"
    bin_directory.mkdir(parents=True)
    runtime_root = bin_directory / managed_install.MANAGED_RUNTIME_PARENT
    runtime_root.mkdir()
    previous = _add_runtime(runtime_root, "v0.2.0rc4.Runtime2")
    current = _add_runtime(runtime_root, "v0.2.0rc5.Runtime1")
    binary = current / "signalweave"
    launcher = bin_directory / "signalweave"
    launcher.write_text(managed_install.render_launcher(binary))
    launcher.chmod(0o755)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(binary))
    return {
        "binary": binary,
        "launcher": launcher,
        "runtime_root": runtime_root,
        "runtimes": (previous, current),
        "home": home,
        "key": key,
    }


def test_render_launcher_escapes_double_quoted_shell_content(tmp_path):
    binary = tmp_path / 'signal\\weave $HOME "quoted" `tick`'
    escaped = str(binary)
    for character, replacement in (("\\", "\\\\"), ("$", "\\$"), ('"', '\\"'), ("`", "\\`")):
        escaped = escaped.replace(character, replacement)
    assert managed_install.render_launcher(binary) == (
        '#!/bin/sh\n# SignalWeave managed runtime v1\n'
        f'exec "{escaped}" "$@"\n'
    )


def test_uninstall_removes_launcher_and_both_retained_runtimes(managed_install_fixture, capsys):
    install = managed_install_fixture
    assert uninstall.uninstall(yes=True)
    assert not install["launcher"].exists()
    assert not any(path.exists() for path in install["runtimes"])
    assert not install["runtime_root"].exists()
    assert install["home"].exists()
    assert install["key"].exists()
    output = capsys.readouterr().out
    assert f"Remove command launcher: {install['launcher']}" in output
    for runtime in install["runtimes"]:
        assert f"Remove managed runtime: {runtime}" in output
    assert "private-test-key" not in output


def test_command_path_stays_stable_across_runtime_upgrade(managed_install_fixture):
    install = managed_install_fixture
    old_command = managed_install.command_path(install["binary"])
    upgraded_runtime = _add_runtime(install["runtime_root"], "v0.2.0rc6.BuildNxt")
    upgraded_binary = upgraded_runtime / "signalweave"
    install["launcher"].write_text(managed_install.render_launcher(upgraded_binary))

    new_command = managed_install.command_path(upgraded_binary)
    assert old_command == install["launcher"]
    assert new_command == old_command


def test_command_path_preserves_unmanaged_executable_path():
    executable = Path(".venv/bin/signalweave")
    assert managed_install.command_path(executable) is executable


def test_command_path_rejects_malformed_managed_hierarchy(managed_install_fixture):
    install = managed_install_fixture
    malformed = install["runtime_root"] / "v0.2.0rc5.invalid" / "signalweave"
    with pytest.raises(local_setup.SetupError):
        managed_install.command_path(malformed)


def test_custom_quoted_install_dir_command_path_and_uninstall(
    managed_install_fixture, monkeypatch, capsys
):
    install = managed_install_fixture
    custom_bin = install["launcher"].parent.parent / 'tools "quoted" $HOME `tick` \\ dir'
    install["launcher"].parent.rename(custom_bin)
    runtime_root = custom_bin / managed_install.MANAGED_RUNTIME_PARENT
    runtimes = tuple(runtime_root / runtime.name for runtime in install["runtimes"])
    current_binary = runtimes[1] / "signalweave"
    launcher = custom_bin / "signalweave"
    launcher.write_text(managed_install.render_launcher(current_binary))
    monkeypatch.setattr(sys, "executable", str(current_binary))

    assert managed_install.command_path(current_binary) == launcher
    assert '\\"quoted\\"' in launcher.read_text()
    assert "\\$HOME" in launcher.read_text()
    assert "\\`tick\\`" in launcher.read_text()
    assert uninstall.uninstall(yes=True)
    assert not launcher.exists()
    assert not any(runtime.exists() for runtime in runtimes)
    assert not runtime_root.exists()
    assert custom_bin.is_dir()
    assert install["home"].exists()
    assert "Remove command launcher:" in capsys.readouterr().out


def test_command_path_skips_validation_of_retained_runtimes(managed_install_fixture):
    install = managed_install_fixture
    old_marker = install["runtimes"][0] / managed_install.MANAGED_MARKER_NAME
    old_marker.write_bytes(b"invalid old marker")

    assert managed_install.command_path(install["binary"]) == install["launcher"]
    with pytest.raises(local_setup.SetupError, match="marker"):
        uninstall.uninstall(yes=True)


def test_runtime_version_requires_ascii_digits(managed_install_fixture):
    install = managed_install_fixture
    non_ascii = install["runtime_root"] / "v٠.2.0rc5.ABC12345" / "signalweave"
    with pytest.raises(local_setup.SetupError, match="directory name"):
        managed_install.command_path(non_ascii)


@pytest.mark.parametrize("artifact", ["marker", "launcher"])
def test_oversized_marker_and_launcher_are_rejected_before_read(
    managed_install_fixture, monkeypatch, artifact
):
    install = managed_install_fixture
    path = (
        install["binary"].parent / managed_install.MANAGED_MARKER_NAME
        if artifact == "marker"
        else install["launcher"]
    )
    path.write_bytes(b"x" * 100_000)
    original_open = Path.open

    def fail_if_read(candidate, *args, **kwargs):
        if candidate == path:
            pytest.fail(f"oversized {artifact} was read")
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_if_read)
    with pytest.raises(local_setup.SetupError):
        managed_install.command_path(install["binary"])


def test_uninstall_cancel_preserves_managed_install(managed_install_fixture, monkeypatch):
    install = managed_install_fixture
    monkeypatch.setattr(sys, "stdin", type("Terminal", (), {"isatty": lambda _: True})())
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert not uninstall.uninstall()
    assert install["launcher"].exists()
    assert all(path.exists() for path in install["runtimes"])


def test_uninstall_rejects_repointed_launcher(managed_install_fixture):
    install = managed_install_fixture
    install["launcher"].write_text("#!/bin/sh\nexec /tmp/other\n")
    install["launcher"].chmod(0o755)
    with pytest.raises(local_setup.SetupError, match="launcher changed"):
        uninstall.uninstall(yes=True)
    assert install["launcher"].exists()
    assert all(path.exists() for path in install["runtimes"])


def test_uninstall_rejects_marker_mismatch(managed_install_fixture):
    install = managed_install_fixture
    marker = install["binary"].parent / managed_install.MANAGED_MARKER_NAME
    marker.write_text("not a SignalWeave marker\n")
    with pytest.raises(local_setup.SetupError, match="marker"):
        uninstall.uninstall(yes=True)
    assert install["launcher"].exists()
    assert all(path.exists() for path in install["runtimes"])


def test_uninstall_rejects_symlink_inside_candidate_runtime(managed_install_fixture, tmp_path):
    install = managed_install_fixture
    target = tmp_path / "outside"
    target.write_text("keep")
    (install["runtimes"][0] / "unexpected-link").symlink_to(target)
    with pytest.raises(local_setup.SetupError, match="symlinks"):
        uninstall.uninstall(yes=True)
    assert target.read_text() == "keep"
    assert all(path.exists() for path in install["runtimes"])


def test_uninstall_rejects_foreign_owned_runtime_content(managed_install_fixture, monkeypatch):
    install = managed_install_fixture
    marker = install["runtimes"][0] / managed_install.MANAGED_MARKER_NAME
    original_lstat = Path.lstat
    foreign_uid = os.getuid() + 1

    def lstat_with_foreign_marker(path):
        info = original_lstat(path)
        if path == marker:
            return SimpleNamespace(st_mode=info.st_mode, st_uid=foreign_uid)
        return info

    monkeypatch.setattr(Path, "lstat", lstat_with_foreign_marker)
    with pytest.raises(local_setup.SetupError, match="owned by the current user"):
        uninstall.uninstall(yes=True)
    assert all(path.exists() for path in install["runtimes"])


def test_uninstall_rejects_special_runtime_content(managed_install_fixture):
    install = managed_install_fixture
    os.mkfifo(install["runtimes"][0] / "unexpected-pipe")
    with pytest.raises(local_setup.SetupError, match="regular files or directories"):
        uninstall.uninstall(yes=True)
    assert all(path.exists() for path in install["runtimes"])


def test_unknown_runtime_root_entries_survive_uninstall(managed_install_fixture, tmp_path):
    install = managed_install_fixture
    note = install["runtime_root"] / "keep-this-file"
    note.write_text("unrelated")
    unrelated = install["runtime_root"] / "custom-folder"
    unrelated.mkdir()
    unknown_symlink = install["runtime_root"] / "custom-link"
    unknown_symlink.symlink_to(tmp_path, target_is_directory=True)

    assert uninstall.uninstall(yes=True)
    assert note.read_text() == "unrelated"
    assert unrelated.is_dir()
    assert unknown_symlink.is_symlink()
    assert install["runtime_root"].is_dir()


def test_uninstall_refuses_more_than_128_managed_candidates(managed_install_fixture):
    install = managed_install_fixture
    for index in range(127):
        _add_runtime(install["runtime_root"], f"v1.0.0.{index:08d}")
    with pytest.raises(local_setup.SetupError, match="more than 128"):
        uninstall.uninstall(yes=True)
    assert install["launcher"].exists()
    assert all(path.exists() for path in install["runtimes"])


def test_uninstall_leaves_unknown_candidate_shaped_file(managed_install_fixture):
    install = managed_install_fixture
    unknown = install["runtime_root"] / "notes.txt"
    unknown.write_text("keep")
    assert uninstall.uninstall(yes=True)
    assert unknown.read_text() == "keep"
    assert install["runtime_root"].exists()
