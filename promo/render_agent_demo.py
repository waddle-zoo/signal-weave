"""Render the SignalWeave pushed-analytics story as five focused browser pages."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

WIDTH, HEIGHT, FPS, DURATION = 1280, 720, 15, 22.0
BG, PANEL, INK, INK_SOFT, MUTED, FAINT, LINE = "#F5F7FA", "#FFFFFF", "#101828", "#344054", "#667085", "#98A2B3", "#E4E7EC"
TEAL, INDIGO, ORANGE, PINK, RED, GREEN = "#12B8A6", "#6366F1", "#F79009", "#EC4A9D", "#D92D20", "#039855"


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def ease(value: float) -> float:
    value = clamp(value)
    return value * value * (3 - 2 * value)


def reveal(start: float, end: float, now: float) -> float:
    return ease((now - start) / max(end - start, 0.001))


def esc(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def attrs(values: dict[str, object]) -> str:
    return " ".join(f'{key.replace("_", "-")}="{esc(value)}"' for key, value in values.items())


def text(x: float, y: float, value: str, size: float, color: str = INK, **kwargs: object) -> str:
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" {attrs(kwargs)}>{esc(value)}</text>'


def rect(x: float, y: float, width: float, height: float, fill: str = PANEL, radius: float = 12, **kwargs: object) -> str:
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" fill="{fill}" {attrs(kwargs)}/>'


def line(x1: float, y1: float, x2: float, y2: float, stroke: str = LINE, width: float = 1, **kwargs: object) -> str:
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{width}" {attrs(kwargs)}/>'


def circle(x: float, y: float, radius: float, fill: str, **kwargs: object) -> str:
    return f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{fill}" {attrs(kwargs)}/>'


def logo() -> str:
    return "".join([
        '<g transform="translate(72 52)">',
        f'<path d="M8 18 C20 2 28 2 40 18 S60 34 72 18" fill="none" stroke="{TEAL}" stroke-width="6" stroke-linecap="round"/>',
        f'<path d="M8 18 C20 34 28 34 40 18 S60 2 72 18" fill="none" stroke="{PINK}" stroke-width="6" stroke-linecap="round"/>',
        f'<path d="M8 18 H72" fill="none" stroke="{INK}" stroke-opacity=".18" stroke-width="3"/>',
        circle(8, 18, 4, INK), circle(72, 18, 4, INK),
        text(91, 20, "SignalWeave", 18, INK, font_family="Arial", font_weight="700", letter_spacing="-0.5"),
        text(92, 36, "EVIDENCE · JUDGMENT · ACTION", 7, MUTED, font_family="Arial", font_weight="700", letter_spacing="1.4"),
        "</g>",
    ])


def shell(now: float, page: int) -> str:
    names = ["SCHEDULED RUN", "HUMAN CONTEXT", "EVIDENCE GRAPH", "BUNDLE TO CODEX", "PUSH + ACK"]
    parts = [
        rect(40, 28, 1200, 664, PANEL, 22, stroke=LINE, stroke_width=1), logo(),
        circle(64, 56, 4, ORANGE), circle(78, 56, 4, TEAL), circle(92, 56, 4, INDIGO),
        rect(288, 42, 590, 28, "#F9FAFB", 8, stroke=LINE, stroke_width=1),
        text(583, 60, "agent session / Codex / SignalWeave MCP", 10, MUTED, text_anchor="middle", font_family="Arial"),
        text(1208, 59, "recording · 00:22", 9, MUTED, text_anchor="end", font_family="Arial", font_weight="700", letter_spacing=".8"),
        text(1208, 77, "scheduled run", 8, TEAL, text_anchor="end", font_family="Arial", font_weight="700", letter_spacing="1.1"),
        line(72, 102, 1208, 102, LINE, 1), line(72, 126, 94, 126, INDIGO, 2),
        text(108, 130, f"0{page + 1}", 10, MUTED, font_family="Arial", font_weight="700", letter_spacing="1.6"),
        text(142, 130, names[page], 10, MUTED, font_family="Arial", font_weight="700", letter_spacing="1.6"),
        text(1208, 680, f"{now:04.1f}s", 10, FAINT, text_anchor="end", font_family="Arial"),
    ]
    for index in range(5):
        x = 520 + index * 40
        parts.append(rect(x, 676, 30 if index == page else 24, 3, INDIGO if index == page else "#D0D5DD", 2))
    return "".join(parts)


def page_header(kicker: str, right: str) -> str:
    return "".join([
        text(72, 176, kicker, 10, INDIGO, font_family="Arial", font_weight="700", letter_spacing="1.6"),
        text(1208, 176, right, 10, MUTED, text_anchor="end", font_family="Arial", font_weight="700", letter_spacing="1.3"),
    ])


def page_scheduled(now: float) -> str:
    query = "What changed in revenue this week, and should we act?"
    query_visible = query[: int(len(query) * reveal(.7, 3.0, now))]
    parts = [
        page_header("PUSHED ANALYTICS", "CODEX / 06:00"), rect(72, 194, 1136, 422, PANEL, 18, stroke=LINE, stroke_width=1),
        text(104, 300, "No one asked.", 48, INK, font_family="Arial", font_weight="700", letter_spacing="-2.6"),
        text(104, 350, "Codex woke up.", 48, INK, font_family="Arial", font_weight="700", letter_spacing="-2.6"),
        text(104, 386, "A scheduled agent loads a human-curated card and starts the run.", 12, MUTED, font_family="Arial"),
        text(104, 432, "AGENT QUERY", 9, INDIGO, font_family="Arial", font_weight="700", letter_spacing="1.4"),
        rect(104, 448, 570, 72, "#FBFBFF", 12, stroke="#BFC7FF", stroke_width=1), text(123, 490, query_visible, 17, INK, font_family="Arial", font_weight="700"),
        rect(756, 248, 390, 92, "#FCFCFD", 14, stroke=LINE, stroke_width=1), text(778, 275, "GROWTH-HEALTH", 9, INK, font_family="Arial", font_weight="700", letter_spacing="1.3"),
        text(1124, 275, "SCHEDULED", 9, MUTED, text_anchor="end", font_family="Arial", font_weight="700", letter_spacing="1.2"), text(778, 310, "Human intent already loaded.", 21, INK, font_family="Arial", font_weight="700", letter_spacing="-.8"), text(778, 326, "card · sources · delivery path", 10, MUTED, font_family="Arial"),
    ]
    steps = [("load the card", INDIGO), ("inspect the evidence", TEAL), ("ask Jev", ORANGE), ("return the bundle", PINK)]
    for index, (label, color) in enumerate(steps):
        active = reveal(1.0 + index * .55, 1.45 + index * .55, now)
        y = 384 + index * 39
        parts += [rect(756, y, 390, 29, PANEL, 8, stroke=LINE if active < .8 else "#B7EBDF", stroke_width=1, opacity=.42 + .58 * active), circle(770, y + 14, 7, color, opacity=.18 + .82 * active), text(770, y + 17, str(index + 1), 8, color, text_anchor="middle", font_family="Arial", font_weight="700", opacity=active), text(790, y + 18, label, 10, INK, font_family="Arial", font_weight="700", opacity=active)]
    return "".join(parts)


def page_card(now: float) -> str:
    parts = [
        page_header("THE CARD IS THE CONTEXT", "FREE-FORM CARD → TYPED JUDGMENT"), rect(72, 194, 1136, 422, PANEL, 18, stroke=LINE, stroke_width=1),
        text(104, 252, "People define what matters.", 39, INK, font_family="Arial", font_weight="700", letter_spacing="-2.0"), text(104, 294, "Jev makes it usable.", 39, INK, font_family="Arial", font_weight="700", letter_spacing="-2.0"),
        text(104, 324, "Human intent in. A typed outcome the agent can use.", 12, MUTED, font_family="Arial"), rect(104, 358, 500, 222, "#FCFCFD", 14, stroke=LINE, stroke_width=1),
        text(126, 386, "GROWTH-HEALTH", 10, INK, font_family="Arial", font_weight="700", letter_spacing="1.4"), text(578, 386, "APPROVED · V7", 9, MUTED, text_anchor="end", font_family="Arial", font_weight="700", letter_spacing="1.1"),
    ]
    fields = [("WHAT TO WATCH", "Weekly revenue movement and the signals that explain a meaningful change."), ("WHY IT MATTERS", "Leadership needs an early signal when the growth plan is drifting."), ("DELIVER BASED ON OUTCOMES", "Notify the right owner only when the evidence supports it.")]
    for index, (label, value) in enumerate(fields):
        y = 418 + index * 52
        parts += [text(126, y, label, 8, INDIGO, font_family="Arial", font_weight="700", letter_spacing="1.1"), text(126, y + 20, value, 10, INK_SOFT, font_family="Arial"), line(126, y + 32, 578, y + 32, LINE, 1, opacity=.8)]
    parts += [rect(680, 294, 466, 230, "#FBFBFF", 14, stroke="#BFC7FF", stroke_width=1), text(706, 324, "TYPESAFE / JEV", 9, INDIGO, font_family="Arial", font_weight="700", letter_spacing="1.5"), text(706, 355, "A judgment the agent can trust.", 22, INK, font_family="Arial", font_weight="700", letter_spacing="-.9"), rect(706, 378, 414, 106, PANEL, 9, stroke="#DFE3FF", stroke_width=1), text(724, 401, 'verdict:     "notify"', 11, INK_SOFT, font_family="Courier New"), text(724, 422, "confidence:  0.91", 11, INK_SOFT, font_family="Courier New"), text(724, 443, "probabilities: notify .91 · review .07", 11, INK_SOFT, font_family="Courier New"), text(724, 464, "evidence:    4 sources", 11, INK_SOFT, font_family="Courier New"), text(724, 485, 'next:        "send + investigate"', 11, INK_SOFT, font_family="Courier New"), text(706, 512, "structured output · provenance attached", 10, MUTED, font_family="Arial")]
    return "".join(parts)


def network_node(x: float, y: float, label: str, note: str, color: str, active: float, radius: float = 28) -> str:
    return "".join([circle(x, y, radius, PANEL, stroke=color, stroke_width=2, opacity=.25 + .75 * active), circle(x, y, 6, color, opacity=.18 + .82 * active), text(x, y + radius + 17, label, 10, INK if active > .5 else MUTED, text_anchor="middle", font_family="Arial", font_weight="700", opacity=.35 + .65 * active), text(x, y + radius + 31, note, 8, FAINT, text_anchor="middle", font_family="Arial", opacity=.35 + .65 * active)])


def page_graph(now: float) -> str:
    active = reveal(7.0, 9.0, now)
    parts = [page_header("JEV FINDS THE CONNECTED EVIDENCE", "CONNECT → QUERY → JUDGE"), rect(72, 194, 1136, 422, "#FCFCFD", 18, stroke=LINE, stroke_width=1)]
    for x in range(104, 1180, 34):
        parts.append(line(x, 218, x, 586, "#F0F2F5", 1))
    for y in range(236, 587, 34):
        parts.append(line(104, y, 1180, y, "#F0F2F5", 1))
    cx, cy = 650, 388
    sources = [(264, 388, "CARD", "human intent", INDIGO), (650, 250, "SQL", "bounded query", INDIGO), (1010, 300, "SUPERSET", "dashboard", ORANGE), (1010, 388, "FUNNEL", "conversion", TEAL), (1010, 476, "OPS", "support + finance", PINK)]
    for index, (x, y, label, note, color) in enumerate(sources):
        edge = reveal(6.8 + index * .42, 7.3 + index * .42, now)
        parts += [line(cx, cy, x, y, "#AAB5EF", 2, opacity=.15 + .85 * edge), circle(cx + (x - cx) * edge, cy + (y - cy) * edge, 5, color, opacity=edge), network_node(x, y, label, note, color, edge, 27)]
    parts += [circle(cx, cy, 52, "#EFF4FF", stroke="#BFC7FF", stroke_width=2, opacity=.72 + .28 * active), text(cx, cy + 7, "Jev", 25, INDIGO, text_anchor="middle", font_family="Arial", font_weight="700", opacity=.72 + .28 * active), text(cx, cy + 25, "JUDGMENT", 8, "#6872D8", text_anchor="middle", font_family="Arial", font_weight="700", letter_spacing="1.4", opacity=.72 + .28 * active)]
    sql = reveal(8.4, 9.0, now)
    parts += [rect(430, 548, 440, 34, PANEL, 8, stroke=LINE, stroke_width=1, opacity=sql), text(448, 570, "SQL", 9, TEAL, font_family="Arial", font_weight="700", letter_spacing="1.0", opacity=sql), text(486, 570, "SELECT revenue, conversion FROM trusted_sources", 10, INK_SOFT, font_family="Courier New", opacity=sql)]
    return "".join(parts)


def page_bundle(now: float) -> str:
    parts = [page_header("THE RESULT IS A DECISION SURFACE", "EVIDENCE, CONFIDENCE, NEXT INSTRUCTION"), rect(72, 194, 1136, 422, PANEL, 18, stroke=LINE, stroke_width=1), text(104, 263, "Facts, confidence,", 41, INK, font_family="Arial", font_weight="700", letter_spacing="-2.1"), text(104, 306, "next instruction.", 41, INK, font_family="Arial", font_weight="700", letter_spacing="-2.1"), text(104, 338, "The sources resolve into one compact bundle for Codex.", 12, MUTED, font_family="Arial"), rect(104, 372, 560, 196, "#FCFCFD", 14, stroke=LINE, stroke_width=1), text(128, 400, "GROWTH-HEALTH / RESULT", 9, INK, font_family="Arial", font_weight="700", letter_spacing="1.2"), text(638, 400, "JEV", 9, MUTED, text_anchor="end", font_family="Arial", font_weight="700", letter_spacing="1.2")]
    rows = [("revenue", "−22%", RED), ("conversion", "−15%", RED), ("support backlog", "+28%", ORANGE), ("finance", "agrees", GREEN)]
    for index, (label, value, color) in enumerate(rows):
        row_a = reveal(10.2 + index * .34, 10.65 + index * .34, now)
        y = 432 + index * 32
        parts += [line(128, y - 17, 638, y - 17, LINE, 1, opacity=row_a), circle(136, y - 2, 5, color, opacity=row_a), text(152, y + 2, label, 11, INK_SOFT, font_family="Arial", font_weight="700", opacity=row_a), text(628, y + 2, value, 13, color, text_anchor="end", font_family="Arial", font_weight="700", opacity=row_a)]
    footer_a = reveal(11.7, 12.3, now)
    parts += [rect(128, 532, 510, 24, "#ECFDF3", 7, opacity=footer_a), text(142, 549, "confidence", 9, GREEN, font_family="Arial", font_weight="700", opacity=footer_a), text(624, 549, "0.91 · notify", 10, GREEN, text_anchor="end", font_family="Arial", font_weight="700", opacity=footer_a)]
    side_a = reveal(11.0, 12.0, now)
    parts += [rect(760, 302, 376, 176, "#FBFBFF", 14, stroke="#BFC7FF", stroke_width=1, opacity=side_a), text(786, 332, "TYPED RESULT", 9, INDIGO, font_family="Arial", font_weight="700", letter_spacing="1.4", opacity=side_a), text(786, 372, "Send to growth", 23, INK, font_family="Arial", font_weight="700", letter_spacing="-.9", opacity=side_a), text(786, 398, "leadership.", 23, INK, font_family="Arial", font_weight="700", letter_spacing="-.9", opacity=side_a), text(786, 432, "Evidence attached.", 10, MUTED, font_family="Arial", opacity=side_a), text(786, 454, "receipt: safe to replay", 10, INDIGO, font_family="Courier New", opacity=side_a)]
    packet = reveal(12.1, 13.3, now)
    if packet:
        parts += [line(760, 560, 420, 560, INDIGO, 2, opacity=packet), circle(760 - 340 * packet, 560, 6, INDIGO, opacity=packet)]
    return "".join(parts)


def page_slack(now: float) -> str:
    message = reveal(15.9, 17.0, now)
    ack = reveal(18.0, 19.0, now)
    foot = reveal(19.2, 20.0, now)
    return "".join([page_header("CODEX → SLACK → HUMAN", "PUSH + ACKNOWLEDGEMENT"), rect(260, 224, 760, 344, PANEL, 17, stroke=LINE, stroke_width=1), line(260, 270, 1020, 270, LINE, 1), text(284, 254, "#growth-leadership", 12, INK, font_family="Arial", font_weight="700"), text(996, 254, "Codex sent evidence", 10, MUTED, text_anchor="end", font_family="Arial"), rect(510, 304, 448, 64, "#EFF4FF", 12, opacity=message), text(532, 330, "CODEX", 9, INDIGO, font_family="Arial", font_weight="700", letter_spacing="1.0", opacity=message), text(532, 351, "Revenue drift is meaningful. Evidence attached.", 11, INK_SOFT, font_family="Arial", opacity=message), rect(286, 398, 420, 62, "#ECFDF3", 12, opacity=ack), text(308, 423, "GROWTH LEADERSHIP", 9, GREEN, font_family="Arial", font_weight="700", letter_spacing="1.0", opacity=ack), text(308, 444, "Ack — looking into it!", 11, INK_SOFT, font_family="Arial", opacity=ack), line(260, 526, 1020, 526, LINE, 1), circle(284, 545, 4, GREEN, opacity=foot), text(298, 549, "human response received", 10, GREEN, font_family="Arial", font_weight="700", opacity=foot)])


def page_for(now: float) -> tuple[int, float, str]:
    boundaries = [0.0, 5.2, 8.2, 12.5, 16.5]
    page = max(index for index, start in enumerate(boundaries) if now >= start)
    content = [page_scheduled, page_card, page_graph, page_bundle, page_slack][page](now)
    return page, boundaries[page], content


def frame(now: float) -> str:
    page, page_start, content = page_for(now)
    enter = reveal(page_start, page_start + .65, now)
    offset = (1 - enter) * 28
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">', f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{BG}"/>', '<g font-family="Arial, Helvetica, sans-serif">', shell(now, page), f'<g opacity="{.24 + .76 * enter}" transform="translate(0 {offset})">', content, '</g>']
    for start in (5.0, 8.0, 12.3, 16.3):
        progress = (now - start) / .8
        if 0 <= progress <= 1:
            x = -120 + 1520 * ease(progress)
            parts += [rect(x, 112, 22, 520, TEAL, 10, opacity=.22 * (1 - progress)), rect(x + 20, 112, 14, 520, INDIGO, 7, opacity=.34 * (1 - progress)), rect(x + 34, 112, 10, 520, PINK, 5, opacity=.2 * (1 - progress))]
    parts += ['</g></svg>']
    return "".join(parts)


def render(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="signalweave-agent-story-") as temp:
        temp_dir = Path(temp)
        for index in range(int(FPS * DURATION)):
            svg = temp_dir / f"frame-{index:05d}.svg"
            png = temp_dir / f"frame-{index:05d}.png"
            svg.write_text(frame(index / FPS), encoding="utf-8")
            subprocess.run(["rsvg-convert", "-o", str(png), str(svg)], check=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", str(temp_dir / "frame-%05d.png"), "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-movflags", "+faststart", str(output)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/promo/signalweave-agent-demo.mp4"))
    args = parser.parse_args()
    render(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
