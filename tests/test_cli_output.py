import io
import json
import sys

import pytest

from signalweave import cli
from signalweave.cli_output import emphasis, progress


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize("no_color,term,colored", [(None, "xterm", True), ("1", "xterm", False), (None, "dumb", False)])
def test_emphasis_obeys_terminal_preferences(monkeypatch, no_color, term, colored):
    monkeypatch.delenv("NO_COLOR", raising=False)
    if no_color:
        monkeypatch.setenv("NO_COLOR", no_color)
    monkeypatch.setenv("TERM", term)
    assert ("\033[" in emphasis("Heading", stream=Terminal())) is colored
    assert emphasis("Heading", stream=io.StringIO()) == "Heading"


def test_progress_is_stderr_only_and_absent_in_pipes(monkeypatch):
    stdout, stderr = Terminal(), Terminal()
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    progress("Checking sources...")
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "Checking sources...\n"
    pipe = io.StringIO()
    monkeypatch.setattr(sys, "stderr", pipe)
    progress("Do not print")
    assert pipe.getvalue() == ""


def test_status_is_short_and_does_not_show_unused_jev_as_missing(monkeypatch, capsys):
    cli._print_status({"status": "ready_for_agent", "decision_provider": {"selected": "openai-decisions", "status": "configured"},
                       "jev": {"status": "missing"}, "credentials": {"OPENAI_API_KEY": "configured", "TYPESAFE_API_KEY": "missing"},
                       "domain_context": {"status": "disabled"}, "connections": []})
    text = capsys.readouterr().out
    assert "openai-decisions (configured)" in text
    assert "Jev:" not in text and "TYPESAFE_API_KEY" not in text
    assert "Shared context: disabled" in text
    assert "\033" not in text


def test_json_status_stays_json_even_in_a_color_terminal(monkeypatch):
    out = Terminal()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(sys, "argv", ["signalweave", "status", "--json"])
    expected = {"status": "setup_required", "next_steps": ["Run setup"]}
    monkeypatch.setattr(cli, "local_status", lambda _: expected)
    cli.main()
    assert json.loads(out.getvalue()) == expected
    assert "\033" not in out.getvalue()
