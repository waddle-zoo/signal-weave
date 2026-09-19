"""Render the 30-second SignalWeave promo motion graphic.

The output is intentionally product-shaped rather than a fake application
screenshot: it communicates the decision loop the real service implements.
Run from the repository root:

    python promo/render_signalweave_demo.py --output artifacts/promo/signalweave-30s.mp4

The script requires ffmpeg and rsvg-convert, both available on macOS with
Homebrew. A voiceover can be mixed in separately with the system ``say`` tool.
"""

from __future__ import annotations

import argparse
import math
import subprocess
import tempfile
from pathlib import Path

WIDTH = 1080
HEIGHT = 1080
FPS = 10
DURATION = 30

BG = "#080B13"
PANEL = "#111827"
PANEL_2 = "#172033"
TEXT = "#F7FAFF"
MUTED = "#9AA8BF"
PURPLE = "#9B8CFF"
CYAN = "#58E1D0"
GREEN = "#6EE7A5"
AMBER = "#FFCB70"
RED = "#FF6F91"


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def ease(value: float) -> float:
    value = clamp(value)
    return value * value * (3 - 2 * value)


def reveal(start: float, end: float, now: float) -> float:
    return ease((now - start) / max(end - start, 0.001))


def fade_in(start: float, end: float, now: float) -> float:
    return reveal(start, end, now)


def fade_out(start: float, end: float, now: float) -> float:
    return 1 - reveal(start, end, now)


def esc(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def text(x: float, y: float, value: str, size: float, color: str = TEXT, **attrs: object) -> str:
    extra = " ".join(f'{key.replace("_", "-")}="{esc(value)}"' for key, value in attrs.items())
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" {extra}>{esc(value)}</text>'


def rect(x: float, y: float, width: float, height: float, fill: str, radius: float = 0, **attrs: object) -> str:
    extra = " ".join(f'{key.replace("_", "-")}="{esc(value)}"' for key, value in attrs.items())
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" fill="{fill}" {extra}/>'


def line(x1: float, y1: float, x2: float, y2: float, stroke: str, width: float = 2, **attrs: object) -> str:
    extra = " ".join(f'{key.replace("_", "-")}="{esc(value)}"' for key, value in attrs.items())
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{width}" {extra}/>'


def circle(cx: float, cy: float, radius: float, fill: str, **attrs: object) -> str:
    extra = " ".join(f'{key.replace("_", "-")}="{esc(value)}"' for key, value in attrs.items())
    return f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{fill}" {extra}/>'


def pill(
    x: float,
    y: float,
    label: str,
    color: str,
    width: float | None = None,
    opacity: float = 1.0,
) -> str:
    width = width or max(120, len(label) * 12 + 34)
    return "".join(
        [
            rect(x, y - 27, width, 42, color, 21, opacity=0.16 * opacity),
            circle(x + 18, y - 6, 5, color, opacity=opacity),
            text(x + 32, y + 2, label, 17, color, opacity=opacity, font_family="Arial", font_weight="700"),
        ]
    )


def chart(x: float, y: float, width: float, height: float, *, danger: bool, progress: float) -> str:
    items = [
        line(x, y, x, y + height, "#31405A", 2),
        line(x, y + height, x + width, y + height, "#31405A", 2),
    ]
    points = [(0, 0.57), (0.13, 0.51), (0.26, 0.54), (0.4, 0.42), (0.53, 0.47), (0.67, 0.35)]
    if danger:
        points += [(0.79, 0.48), (0.9, 0.7), (1.0, 0.86)]
    else:
        points += [(0.79, 0.31), (0.9, 0.26), (1.0, 0.2)]
    visible = max(2, int(len(points) * clamp(progress)))
    path = " ".join(
        ("M" if index == 0 else "L")
        + f" {x + px * width:.1f},{y + py * height:.1f}"
        for index, (px, py) in enumerate(points[:visible])
    )
    items.append(f'<path d="{path}" fill="none" stroke="{RED if danger else CYAN}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>')
    for index, (px, py) in enumerate(points[:visible]):
        if index == visible - 1:
            items.append(circle(x + px * width, y + py * height, 9, RED if danger else CYAN))
    return "".join(items)


def dashboard(
    x: float,
    y: float,
    width: float,
    height: float,
    now: float,
    danger: bool = True,
    opacity: float = 1.0,
) -> str:
    local = reveal(4.3, 8.7, now) if danger else reveal(0, 1, now)
    items = [f'<g opacity="{opacity}">', rect(x, y, width, height, PANEL, 24, stroke="#25324A", stroke_width=2)]
    items += [text(x + 28, y + 42, "EXECUTIVE PULSE", 16, MUTED, font_family="Arial", font_weight="700", letter_spacing="2")]
    items += [text(x + 28, y + 93, "Revenue health", 28, TEXT, font_family="Arial", font_weight="700")]
    items += [pill(x + width - 168, y + 68, "LIVE", GREEN, 112)]
    items += [text(x + 28, y + 148, "$4.82M", 46, TEXT, font_family="Arial", font_weight="700")]
    items += [text(x + 32, y + 178, "vs. previous period", 15, MUTED, font_family="Arial")]
    items += [
        text(x + width - 150, y + 150, "-22.0%", 26, RED if danger else GREEN, font_family="Arial", font_weight="700"),
        text(x + width - 150, y + 178, "material move", 14, MUTED, font_family="Arial"),
    ]
    items += [chart(x + 28, y + 215, width - 56, height - 255, danger=danger, progress=local)]
    items.append("</g>")
    return "".join(items)


def source_card(x: float, y: float, label: str, value: str, color: str, opacity: float = 1.0) -> str:
    return "".join(
        [
            rect(x, y, 245, 104, PANEL, 18, opacity=opacity, stroke="#25324A", stroke_width=2),
            circle(x + 25, y + 30, 7, color, opacity=opacity),
            text(x + 46, y + 36, label, 16, TEXT, opacity=opacity, font_family="Arial", font_weight="700"),
            text(x + 24, y + 77, value, 25, color, opacity=opacity, font_family="Arial", font_weight="700"),
        ]
    )


def scene_intro(now: float) -> str:
    alpha = fade_out(3.3, 4.4, now)
    return "".join(
        [
            text(88, 150, "SIGNALWEAVE", 22, PURPLE, opacity=alpha, font_family="Arial", font_weight="700", letter_spacing="5"),
            text(88, 330, "Dashboards have", 76, TEXT, opacity=alpha, font_family="Arial", font_weight="700"),
            text(88, 415, "signals.", 76, CYAN, opacity=alpha, font_family="Arial", font_weight="700"),
            text(88, 500, "Your team needs decisions.", 48, MUTED, opacity=alpha, font_family="Arial", font_weight="700"),
            line(88, 590, 430, 590, PURPLE, 5, opacity=alpha),
            text(88, 650, "Push-based analytics for the work", 25, TEXT, opacity=alpha, font_family="Arial"),
            text(88, 685, "you already do.", 25, TEXT, opacity=alpha, font_family="Arial"),
        ]
    )


def scene_move(now: float) -> str:
    alpha = fade_in(4.0, 4.7, now) * fade_out(8.4, 9.0, now)
    items = [
        text(84, 112, "A metric moves.", 50, TEXT, opacity=alpha, font_family="Arial", font_weight="700"),
        text(84, 157, "SignalWeave does more than raise an alarm.", 22, MUTED, opacity=alpha, font_family="Arial"),
        dashboard(84, 220, 912, 610, now, danger=True, opacity=alpha),
        pill(84, 915, "REVENUE DOWN 22%", RED, 260, opacity=alpha),
    ]
    return "".join(items)


def scene_evidence(now: float) -> str:
    alpha = fade_in(9.0, 9.7, now) * fade_out(15.4, 16.0, now)
    center_x, center_y = 540, 530
    items = [
        text(84, 112, "It pulls the context together.", 47, TEXT, opacity=alpha, font_family="Arial", font_weight="700"),
        text(84, 157, "Across the sources you already trust.", 22, MUTED, opacity=alpha, font_family="Arial"),
        line(315, 360, center_x, center_y, PURPLE, 3, opacity=alpha),
        line(765, 360, center_x, center_y, CYAN, 3, opacity=alpha),
        line(315, 700, center_x, center_y, AMBER, 3, opacity=alpha),
        line(765, 700, center_x, center_y, GREEN, 3, opacity=alpha),
        circle(center_x, center_y, 86, PANEL_2, stroke=PURPLE, stroke_width=3, opacity=alpha),
        text(center_x - 55, center_y - 8, "Jev", 37, TEXT, opacity=alpha, font_family="Arial", font_weight="700"),
        text(center_x - 60, center_y + 24, "typed judgment", 13, MUTED, opacity=alpha, font_family="Arial"),
        source_card(165, 260, "Superset", "revenue −22%", RED, alpha),
        source_card(670, 260, "Web funnel", "conversion −15%", CYAN, alpha),
        source_card(165, 645, "Support ops", "backlog +28%", AMBER, alpha),
        source_card(670, 645, "Finance", "revenue −21%", GREEN, alpha),
    ]
    return "".join(items)


def scene_decision(now: float) -> str:
    alpha = fade_in(16.0, 16.7, now) * fade_out(21.4, 22.0, now)
    return "".join(
        [
            text(84, 118, "Not another alert.", 55, TEXT, opacity=alpha, font_family="Arial", font_weight="700"),
            text(84, 166, "A decision with evidence.", 30, CYAN, opacity=alpha, font_family="Arial", font_weight="700"),
            rect(84, 250, 912, 450, PANEL, 28, opacity=alpha, stroke="#30415E", stroke_width=2),
            pill(130, 315, "NOTIFY LEADERSHIP", RED, 300, opacity=alpha),
            text(130, 405, "Corroborated material decline", 37, TEXT, opacity=alpha, font_family="Arial", font_weight="700"),
            text(130, 458, "4 related sources agree.", 25, MUTED, opacity=alpha, font_family="Arial"),
            line(130, 510, 950, 510, "#30415E", 2, opacity=alpha),
            text(130, 568, "Why", 17, PURPLE, opacity=alpha, font_family="Arial", font_weight="700", letter_spacing="2"),
            text(130, 610, "Revenue, funnel, support, and finance", 25, TEXT, opacity=alpha, font_family="Arial"),
            text(130, 646, "tell the same story.", 25, TEXT, opacity=alpha, font_family="Arial"),
        ]
    )


def scene_holdback(now: float) -> str:
    alpha = fade_in(22.0, 22.7, now) * fade_out(26.6, 27.2, now)
    return "".join(
        [
            text(84, 116, "And it knows when to hold back.", 43, TEXT, opacity=alpha, font_family="Arial", font_weight="700"),
            text(84, 164, "Because noise is expensive.", 24, MUTED, opacity=alpha, font_family="Arial"),
            rect(84, 260, 410, 330, PANEL, 25, opacity=alpha, stroke="#30415E", stroke_width=2),
            pill(120, 330, "INVESTIGATE", AMBER, 215, opacity=alpha),
            text(120, 410, "Conflicting sources", 28, TEXT, opacity=alpha, font_family="Arial", font_weight="700"),
            text(120, 454, "Route to analytics.", 23, MUTED, opacity=alpha, font_family="Arial"),
            rect(586, 260, 410, 330, PANEL, 25, opacity=alpha, stroke="#30415E", stroke_width=2),
            pill(622, 330, "IGNORE", GREEN, 145, opacity=alpha),
            text(622, 410, "Normal movement", 28, TEXT, opacity=alpha, font_family="Arial", font_weight="700"),
            text(622, 454, "Keep the inbox quiet.", 23, MUTED, opacity=alpha, font_family="Arial"),
            text(84, 790, "Human-authored intent. Typed semantic judgment. Code-owned safety.", 24, PURPLE, opacity=alpha, font_family="Arial", font_weight="700"),
        ]
    )


def scene_outro(now: float) -> str:
    alpha = fade_in(27.2, 28.0, now)
    glow = 0.12 + 0.08 * math.sin(now * 4)
    return "".join(
        [
            circle(540, 345, 145, PURPLE, opacity=glow),
            text(540, 365, "SW", 82, TEXT, opacity=alpha, text_anchor="middle", font_family="Arial", font_weight="700"),
            text(540, 535, "Stop checking dashboards.", 52, TEXT, opacity=alpha, text_anchor="middle", font_family="Arial", font_weight="700"),
            text(540, 600, "Start receiving decisions.", 42, CYAN, opacity=alpha, text_anchor="middle", font_family="Arial", font_weight="700"),
            text(540, 730, "SIGNALWEAVE", 25, PURPLE, opacity=alpha, text_anchor="middle", font_family="Arial", font_weight="700", letter_spacing="6"),
            text(540, 775, "Powered by TypeSafe Jev", 19, MUTED, opacity=alpha, text_anchor="middle", font_family="Arial"),
        ]
    )


def frame(now: float) -> str:
    body = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1080" viewBox="0 0 1080 1080">',
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#080B13"/><stop offset="1" stop-color="#10182A"/></linearGradient></defs>',
        '<rect width="1080" height="1080" fill="url(#bg)"/>',
        '<g font-family="Arial, Helvetica, sans-serif">',
    ]
    body.extend(
        [
            scene_intro(now),
            scene_move(now),
            scene_evidence(now),
            scene_decision(now),
            scene_holdback(now),
            scene_outro(now),
            line(84, 1015, 996, 1015, "#26334B", 3),
            line(84, 1015, 84 + 912 * clamp(now / DURATION), 1015, PURPLE, 3),
            text(996, 1048, f"{now:04.1f}s", 16, MUTED, text_anchor="end", font_family="Arial"),
        ]
    )
    body.extend(["</g>", "</svg>"])
    return "".join(body)


def render(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="signalweave-promo-") as temp:
        temp_dir = Path(temp)
        for index in range(FPS * DURATION):
            svg_path = temp_dir / f"frame-{index:05d}.svg"
            png_path = temp_dir / f"frame-{index:05d}.png"
            svg_path.write_text(frame(index / FPS), encoding="utf-8")
            subprocess.run(["rsvg-convert", "-o", str(png_path), str(svg_path)], check=True)
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                str(temp_dir / "frame-%05d.png"),
                "-vf",
                "fps=30,format=yuv420p",
                "-c:v",
                "libx264",
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/promo/signalweave-30s.mp4"))
    args = parser.parse_args()
    render(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
