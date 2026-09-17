from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "resnet50_15fps_shufflenet_v2_500fps" / "ppt_assets"
OUT.mkdir(parents=True, exist_ok=True)

WIDTH = 1600
HEIGHT = 900

INK = "#17202a"
MUTED = "#5d6875"
LINE = "#d8dee6"
SOFT = "#f5f7fa"
HEADER = "#eef2f6"
GREEN = "#117a65"
BLUE = "#2f6fad"
PURPLE = "#7157a8"
ORANGE = "#b86b1b"
RED = "#a93226"
WHITE = "#ffffff"

GOALS = ("balanced", "latency", "power", "area")


def main() -> None:
    rows = make_rows()
    matches = sum(1 for row in rows if row["same"])

    img, draw = canvas()
    header(
        draw,
        "Pareto-DP preserves the reported best designs",
        "ResNet50 target is 15 FPS; ShuffleNetV2 target is 500 FPS. DP matches brute-force on the selected design metrics.",
    )

    y = 175
    metric_card(draw, 70, y, 340, 112, "Checks passed", f"{matches}/{len(rows)}", "same selected metrics", GREEN)
    metric_card(draw, 430, y, 340, 112, "Models", "2", "ResNet50 @15, ShuffleNetV2 @500 FPS", BLUE)
    metric_card(draw, 790, y, 340, 112, "Goals", "4", "balanced, latency, power, area", PURPLE)
    metric_card(draw, 1150, y, 380, 112, "Use in talk", "Validation", "DP does not change the result", ORANGE)

    panel(draw, 70, 325, 1460, 480)
    columns = [
        ("Goal", 160),
        ("Model", 210),
        ("Target", 120),
        ("Brute-force", 390),
        ("Pareto-DP", 390),
        ("Match", 130),
    ]
    table_rows = [
        [
            goal_name(row["goal"]),
            row["model"],
            row["target"],
            compact_result(row["brute"]),
            compact_result(row["dp"]),
            "same" if row["same"] else "different",
        ]
        for row in rows
    ]
    data_table(draw, 95, 350, columns, table_rows, row_h=47, font_size=18)

    footer(draw)
    output = OUT / "05_search_method_check.png"
    img.save(output)
    print(f"Wrote {output}")


def make_rows() -> list[dict]:
    rows = []
    for goal in GOALS:
        for model_key, model_label, root_name in (
            ("resnet50", "ResNet50", "resnet50_15fps"),
            ("shufflenet_v2_x1_0", "ShuffleNetV2", "shufflenet_v2_500fps"),
        ):
            brute = read_best(root_name, "brute_force", goal)
            dp = read_best(root_name, "pareto_dp", goal)
            rows.append(
                {
                    "goal": goal,
                    "model": model_label,
                    "target": f"{float(brute['target_fps']):.0f} FPS",
                    "brute": brute,
                    "dp": dp,
                    "same": same_design(brute, dp),
                }
            )
    return rows


def read_best(root_name: str, method: str, goal: str) -> dict[str, str]:
    path = ROOT / "results" / root_name / method / goal / "best.csv"
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"No rows in {path}")
    return rows[0]


def same_design(left: dict[str, str], right: dict[str, str]) -> bool:
    keys = ("model", "topology", "status", "used_chiplets", "achieved_fps", "area_mm2", "power_w", "latency_ns")
    return all(left[key] == right[key] for key in keys)


def compact_result(row: dict[str, str]) -> str:
    return f"{row['status']}, {row['used_chiplets']} chiplets, {float(row['achieved_fps']):.2f} FPS"


def header(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    text(draw, title, 70, 48, 46, bold=True)
    wrapped(draw, subtitle, 70, 106, 1240, 24, fill=MUTED)
    text(draw, "integrated report", 1335, 57, 17, fill=MUTED)
    text(draw, "15 FPS + 500 FPS targets", 1335, 82, 17, fill=MUTED)
    draw.line([70, 145, 1530, 145], fill=LINE, width=2)


def metric_card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    label: str,
    value: str,
    note: str,
    color: str,
) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=SOFT, outline=LINE, width=1)
    draw.rectangle([x, y, x + 7, y + h], fill=color)
    text(draw, label, x + 20, y + 16, 18, fill=MUTED)
    text(draw, value, x + 20, y + 45, 32, bold=True)
    wrapped(draw, note, x + 20, y + 86, w - 32, 16, fill=MUTED)


def data_table(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    columns: list[tuple[str, int]],
    rows: list[list[str]],
    row_h: int,
    font_size: int,
) -> None:
    total_w = sum(width for _, width in columns)
    draw.rectangle([x, y, x + total_w, y + row_h], fill=HEADER)
    cx = x
    for title, width in columns:
        text(draw, title, cx + 10, y + 13, font_size, bold=True)
        cx += width
    cy = y + row_h
    for row in rows:
        draw.line([x, cy, x + total_w, cy], fill=LINE, width=1)
        cx = x
        for _, width in columns:
            value = row.pop(0)
            fill = GREEN if value == "same" else RED if value == "different" else INK
            text(draw, value, cx + 10, cy + 13, font_size, bold=value in {"same", "different"}, fill=fill)
            cx += width
        cy += row_h
    draw.line([x, cy, x + total_w, cy], fill=LINE, width=1)


def panel(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=WHITE, outline=LINE, width=1)


def footer(draw: ImageDraw.ImageDraw) -> None:
    text(
        draw,
        "Source: simplified_rapidchiplet/results/resnet50_15fps and results/shufflenet_v2_500fps best.csv files",
        70,
        858,
        15,
        fill=MUTED,
    )


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    return img, ImageDraw.Draw(img)


def wrapped(
    draw: ImageDraw.ImageDraw,
    value: str,
    x: int,
    y: int,
    max_w: int,
    size: int,
    *,
    bold: bool = False,
    fill: str = INK,
) -> None:
    font = font_for(size, bold=bold)
    words = value.split()
    lines: list[str] = []
    line = ""
    for word in words:
        test = word if not line else f"{line} {word}"
        if text_width(draw, test, font) <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    for i, line in enumerate(lines[:3]):
        draw.text((x, y + i * int(size * 1.25)), line, font=font, fill=fill)


def text(
    draw: ImageDraw.ImageDraw,
    value: str,
    x: int,
    y: int,
    size: int,
    *,
    bold: bool = False,
    fill: str = INK,
) -> None:
    draw.text((x, y), value, font=font_for(size, bold=bold), fill=fill)


def text_width(draw: ImageDraw.ImageDraw, value: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), value, font=font)
    return bbox[2] - bbox[0]


def font_for(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/msjhbd.ttc" if bold else "C:/Windows/Fonts/msjh.ttc"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def goal_name(goal: str) -> str:
    return {
        "balanced": "Balanced",
        "latency": "Low latency",
        "power": "Low power",
        "area": "Low area",
    }[goal]


if __name__ == "__main__":
    main()
