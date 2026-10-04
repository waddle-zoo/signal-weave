"""Small loopback-only health UI for a human's local SignalWeave install."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .local_health import live_health_report
from .local_setup import SetupError, local_environment
from .local_status import local_status

_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SignalWeave local status</title>
  <style>
    :root {
      color-scheme: light;
      --paper: #f5f1e9;
      --panel: #fffdf8;
      --ink: #172329;
      --muted: #687477;
      --line: #d9dfda;
      --teal: #0b7c73;
      --teal-soft: #d9f0ea;
      --amber: #a66117;
      --amber-soft: #fae7c9;
      --red: #a54135;
      --red-soft: #f7ddd8;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 0%, rgba(11,124,115,.12), transparent 32rem),
        var(--paper);
    }
    main { max-width: 980px; margin: 0 auto; padding: 48px 22px 70px; }
    header { display: flex; justify-content: space-between; gap: 24px; align-items: end; }
    .eyebrow { color: var(--teal); font-weight: 800; letter-spacing: .13em; text-transform: uppercase; font-size: .72rem; }
    h1 { font-family: Georgia, serif; font-weight: 500; font-size: clamp(2.5rem, 7vw, 5.2rem); line-height: .95; letter-spacing: -.055em; margin: 10px 0 0; }
    .lede { color: var(--muted); max-width: 550px; line-height: 1.55; margin: 18px 0 0; }
    button {
      border: 1px solid var(--ink); border-radius: 999px; background: var(--ink); color: white;
      padding: 11px 17px; font: inherit; cursor: pointer; white-space: nowrap;
    }
    button:hover { background: var(--teal); border-color: var(--teal); }
    button.secondary { background: transparent; color: var(--ink); }
    button.secondary:hover { color: white; }
    button:focus-visible { outline: 3px solid #9bd7cf; outline-offset: 3px; }
    .summary { display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 12px; margin: 36px 0 14px; }
    .card { background: color-mix(in srgb, var(--panel) 94%, transparent); border: 1px solid var(--line); border-radius: 18px; padding: 20px; box-shadow: 0 14px 38px rgba(23,35,41,.05); }
    .summary .card:first-child { background: var(--ink); color: #fffdf8; border-color: var(--ink); }
    .label { color: var(--muted); font-size: .74rem; font-weight: 800; letter-spacing: .11em; text-transform: uppercase; }
    .summary .card:first-child .label { color: #a8c9c2; }
    .value { font-size: 1.65rem; font-weight: 700; margin-top: 12px; }
    .small { color: var(--muted); font-size: .9rem; line-height: 1.45; margin-top: 8px; }
    .summary .card:first-child .small { color: #c2d0ce; }
    section { margin-top: 28px; }
    h2 { font-size: 1.1rem; letter-spacing: -.01em; margin: 0 0 12px; }
    .rows { display: grid; gap: 10px; }
    .row { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 15px 17px; }
    .row-main { min-width: 0; }
    .row-title { font-weight: 700; }
    .row-detail { color: var(--muted); overflow-wrap: anywhere; font-size: .88rem; margin-top: 4px; }
    .pill { flex: 0 0 auto; border-radius: 999px; padding: 5px 9px; font-size: .72rem; font-weight: 800; text-transform: uppercase; letter-spacing: .06em; }
    .pill.configured, .pill.ready, .pill.reachable { color: var(--teal); background: var(--teal-soft); }
    .pill.missing, .pill.not_configured, .pill.setup_required { color: var(--amber); background: var(--amber-soft); }
    .pill.invalid, .pill.error { color: var(--red); background: var(--red-soft); }
    .next { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .next .card { color: var(--muted); font-size: .9rem; line-height: 1.45; }
    code { color: var(--ink); font-size: .84em; background: #edf1ed; padding: 2px 5px; border-radius: 5px; }
    footer { color: var(--muted); font-size: .8rem; margin-top: 34px; }
    @media (max-width: 680px) {
      main { padding: 30px 16px 48px; }
      header { align-items: start; flex-direction: column; }
      .summary, .next { grid-template-columns: 1fr; }
      .row { align-items: start; flex-direction: column; }
    }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; } }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <div class="eyebrow">Local control room</div>
        <h1>Is SignalWeave ready?</h1>
        <p class="lede">A private view of your local setup. Secrets are never rendered here. Use the CLI to change configuration; this page only helps you see what is ready for your agent.</p>
      </div>
      <div class="actions">
        <button id="refresh" type="button">Refresh</button>
        <button id="check" class="secondary" type="button">Check sources</button>
      </div>
    </header>
    <div id="app" aria-live="polite">
      <div class="card" style="margin-top:36px">Loading local status…</div>
    </div>
    <footer id="foot"></footer>
  </main>
  <script>
    const app = document.getElementById("app");
    const foot = document.getElementById("foot");
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
    }[char]));
    const pill = (value) => '<span class="pill ' + esc(value) + '">' + esc(value).replaceAll("_", " ") + "</span>";
    const row = (title, detail, status) =>
      '<div class="card row"><div class="row-main"><div class="row-title">' + esc(title) +
      '</div><div class="row-detail">' + esc(detail || "") + '</div></div>' + pill(status) + "</div>";
    const render = (data) => {
      const connections = (data.connections || []).map((item) =>
        row(item.label, item.endpoint || item.detail || "No connection configured", item.status)).join("");
      const credentials = Object.entries(data.credentials || {}).map(([name, status]) =>
        row(name.replaceAll("_", " "), "Secret value hidden", status)).join("");
      const next = (data.next_steps || []).map((step) =>
        '<div class="card">' + esc(step) + "</div>").join("");
      const error = data.error ? '<div class="card" style="margin-top:12px;color:var(--red)">' + esc(data.error) + "</div>" : "";
      const live = data.live_health ?
        '<section><h2>Source health</h2><div class="card"><div class="value">' +
        (data.live_health.healthy ? 'Reachable' : 'Needs attention') +
        '</div><div class="small">' + (data.live_health.messages || []).map(esc).join('<br>') +
        '</div></div></section>' : '';
      app.innerHTML =
        '<div class="summary">' +
          '<div class="card"><div class="label">Overall</div><div class="value">' + esc(data.status).replaceAll("_", " ") +
            '</div><div class="small">' + esc(data.home) + "</div></div>" +
          '<div class="card"><div class="label">Jev</div><div class="value">' + esc((data.jev || {}).status || "unknown") +
            '</div><div class="small">Configured locally; a live provider check is explicit.</div></div>' +
          '<div class="card"><div class="label">Agent handoff</div><div class="value">MCP</div><div class="small">Use the CLI to register Codex or Claude.</div></div>' +
        '</div>' + error +
        '<section><h2>Connections</h2><div class="rows">' + (connections || row("Sources", "Add a source with the CLI", "not_configured")) + "</div></section>" +
        '<section><h2>Credentials</h2><div class="rows">' + (credentials || row("Credentials", "No local config yet", "missing")) + "</div></section>" +
        '<section><h2>Next steps</h2><div class="next">' + (next || '<div class="card">No next steps.</div>') + "</div></section>" + live;
      foot.textContent = "Home: " + (data.home || "unknown") + " · refreshed " + new Date().toLocaleTimeString();
    };
    const load = async (live = false) => {
      try {
        const response = await fetch("/api/status" + (live ? "?live=true" : ""), { cache: "no-store" });
        if (!response.ok) throw new Error("Status request failed");
        render(await response.json());
      } catch (error) {
        app.innerHTML = '<div class="card" style="margin-top:36px;color:var(--red)">Could not read local status. ' + esc(error.message) + "</div>";
      }
    };
    document.getElementById("refresh").addEventListener("click", () => load(false));
    document.getElementById("check").addEventListener("click", () => load(true));
    load();
  </script>
</body>
</html>"""


def create_local_ui(home: str | Path | None = None) -> Any:
    """Create a no-auth FastAPI app intended to bind only to loopback."""
    app = FastAPI(title="SignalWeave local status", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _PAGE

    @app.get("/api/status")
    async def status(live: bool = False) -> dict[str, Any]:
        report = local_status(home)
        if live and report.get("status") != "setup_required":
            try:
                with local_environment(home):
                    report["live_health"] = await live_health_report()
            except (SetupError, OSError):
                report["live_health"] = {
                    "healthy": False,
                    "messages": ["Live source check could not start; run `signalweave doctor` for details."],
                }
        return report

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


__all__ = ["create_local_ui"]
