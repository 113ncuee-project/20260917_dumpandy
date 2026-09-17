from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "shufflenet_v2_500fps" / "brute_force"
OUT = ROOT / "results" / "shufflenet_v2_500fps" / "ppt_assets"
OUT.mkdir(parents=True, exist_ok=True)

WIDTH = 1036
HEIGHT = 583

INK = "#1e2a36"
MUTED = "#66737f"
LINE = "#d9e1e8"
HEADER = "#eef3f7"
SOFT = "#f8fafc"
BLUE = "#2f73b7"
TITLE_BLUE = "#0088ff"
GREEN = "#0f806a"
RED = "#b1302a"
ORANGE = "#b86b1b"
PURPLE = "#6f55a8"
TEAL = "#4b868a"
WHITE = "#ffffff"

GOALS = ("balanced", "latency", "power", "area")


def main() -> None:
    best = {goal: read_json(RESULTS / goal / "best.json")[0] for goal in GOALS}
    summaries = {goal: read_json(RESULTS / goal / "summary.json") for goal in GOALS}

    draw_result_overview(best)
    draw_partition_overview(best)
    draw_topology_summary(summaries)
    print(f"Wrote ShuffleNetV2 slide images to {OUT}")


def draw_result_overview(best: dict[str, dict]) -> None:
    img, draw = canvas()
    slide_title(draw, "5. ShuffleNetV2  評估結果")

    rows = [best[goal] for goal in GOALS]
    table_x, table_y = 31, 99
    col_w = [103, 82, 72, 155, 83, 142, 135, 94, 60]
    headers = ["Goal", "Topology", "Status", "FPS", "Chiplets", "Area", "Power", "Latency", "PPA"]
    max_fps = max(row["achieved_fps"] for row in rows)
    max_area = max(row["total_area_mm2"] for row in rows)
    max_power = max(row["total_power_w"] for row in rows)

    panel(draw, table_x, 84, 965, 257)
    draw.rectangle([table_x + 16, table_y, table_x + 16 + sum(col_w), table_y + 31], fill=HEADER)
    cx = table_x + 16
    for header, width in zip(headers, col_w):
        text(draw, header, cx + 6, table_y + 8, 14, bold=True)
        cx += width

    row_y = table_y + 31
    for goal, row in zip(GOALS, rows):
        draw.line([table_x + 16, row_y, table_x + 16 + sum(col_w), row_y], fill="#e9eef3", width=1)
        values = [
            goal_name(goal),
            row["topology"],
            "MET" if row["target_met"] else "MISS",
            f"{row['achieved_fps']:.2f}",
            f"{row['selected_chiplets']}/16",
            f"{row['total_area_mm2']:.1f}",
            f"{row['total_power_w']:.1f}",
            f"{row['avg_latency_ns']:.1f} ns",
            f"{row['ppa_score']:.3f}",
        ]
        cx = table_x + 16
        for idx, (value, width) in enumerate(zip(values, col_w)):
            fill = INK
            bold = idx == 0
            if idx == 1:
                fill = RED
                bold = True
            if idx == 2:
                fill = GREEN
                bold = True
            text(draw, value, cx + 6, row_y + 12, 13, bold=bold, fill=fill)
            if idx == 3:
                bar(draw, cx + 58, row_y + 16, 84, 10, row["achieved_fps"], max_fps, GREEN)
            if idx == 5:
                bar(draw, cx + 62, row_y + 16, 74, 10, row["total_area_mm2"], max_area, BLUE)
            if idx == 6:
                bar(draw, cx + 58, row_y + 16, 72, 10, row["total_power_w"], max_power, ORANGE)
            cx += width
        row_y += 46
    draw.line([table_x + 16, row_y, table_x + 16 + sum(col_w), row_y], fill=LINE, width=1)

    card_y = 363
    card_w = 312
    cards = [
        (
            "Feasible choice",
            GREEN,
            "Balanced / power / area use mesh with 9 chiplets and achieve 514.29 FPS.",
        ),
        (
            "Latency choice",
            ORANGE,
            "Low latency uses 10 chiplets and reaches 533.33 FPS with 202.0 ns.",
        ),
        (
            "All choices meet target",
            BLUE,
            "Every user choice meets 500 FPS; there is no FPS penalty.",
        ),
    ]
    for i, (title, color, body) in enumerate(cards):
        x = 31 + i * (card_w + 14)
        panel(draw, x, card_y, card_w, 120)
        text(draw, title, x + 14, card_y + 17, 18, bold=True, fill=color)
        wrapped(draw, body, x + 14, card_y + 50, card_w - 30, 21, bold=True)

    img.save(OUT / "shufflenet_500fps_01_result_overview.png")


def draw_partition_overview(best: dict[str, dict]) -> None:
    img, draw = canvas()
    slide_title(draw, "6. ShuffleNetV2 四種設計方向下的最佳 stage 切分方式")

    shared = best["balanced"]
    latency = best["latency"]
    max_ops = max(
        node["ops"]
        for row in (shared, latency)
        for node in row["connection_graph"]["nodes"]
    )

    partition_band(
        draw,
        "Balanced / Low Power / Low Area",
        shared,
        y=112,
        height=154,
        max_ops=max_ops,
        headline="mesh | 9/16 chiplets | 514.29 FPS | MET | PPA 0.515/0.542/0.544",
        note="Same partition for three goals",
    )
    partition_band(
        draw,
        "Low Latency",
        latency,
        y=333,
        height=154,
        max_ops=max_ops,
        headline="mesh | 10/16 chiplets | 533.33 FPS | MET | PPA 0.443",
        note="Adds one stage3 split to reduce latency",
    )

    img.save(OUT / "shufflenet_500fps_02_stage_partition.png")


def draw_topology_summary(summaries: dict[str, list[dict]]) -> None:
    img, draw = canvas()
    slide_title(draw, "7. ShuffleNetV2  mesh vs tree", boxed=True)
    text(draw, "整體來說 mesh 得出的 ppa score 較好；tree 功耗略低，但延遲較高", 82, 111, 21, font_kind="title")

    table_rows: list[dict] = []
    for goal in GOALS:
        rows = summaries[goal]
        best_score = min(row["ppa_score"] for row in rows)
        for row in rows:
            table_rows.append({**row, "selected": math.isclose(row["ppa_score"], best_score)})

    x, y = 14, 150
    panel(draw, x, y, 1008, 450)
    col_w = [116, 86, 72, 86, 82, 80, 78, 106, 90, 94, 80]
    headers = ["Goal", "Topology", "Status", "Chiplets", "FPS", "Area", "Power", "PPA score", "Latency", "Bottleneck", "Selected"]
    table_x = x + 17
    table_y = y + 28
    total_w = sum(col_w)
    draw.rectangle([table_x, table_y, table_x + total_w, table_y + 42], fill=HEADER)
    cx = table_x
    for header, width in zip(headers, col_w):
        text(draw, header, cx + 7, table_y + 13, 13, bold=True)
        cx += width

    row_y = table_y + 42
    for row in table_rows:
        draw.line([table_x, row_y, table_x + total_w, row_y], fill=LINE, width=1)
        values = [
            goal_name(row["ppa_goal"]),
            row["topology"],
            "MET" if row["target_met"] else "MISS",
            f"{row['selected_chiplets']}/16",
            f"{row['achieved_fps']:.2f}",
            f"{row['total_area_mm2']:.1f}",
            f"{row['total_power_w']:.1f}",
            f"{row['ppa_score']:.3f}",
            f"{row['avg_latency_ns']:.1f} ns",
            row["bottleneck_link"],
            "yes" if row["selected"] else "no",
        ]
        cx = table_x
        for idx, (value, width) in enumerate(zip(values, col_w)):
            fill = INK
            bold = False
            if idx == 2:
                fill = GREEN if value == "MET" else RED
                bold = True
            if idx == 10:
                fill = GREEN if value == "yes" else RED
                bold = True
            text(draw, value, cx + 7, row_y + 12, 13, bold=bold, fill=fill)
            cx += width
        row_y += 41
    draw.line([table_x, row_y, table_x + total_w, row_y], fill=LINE, width=1)

    ppa_x = table_x + sum(col_w[:7])
    draw.rectangle([ppa_x - 3, table_y - 9, ppa_x + col_w[7] + 3, row_y + 10], outline="#ff0000", width=4)

    img.save(OUT / "shufflenet_500fps_03_mesh_vs_tree.png")


def partition_band(
    draw: ImageDraw.ImageDraw,
    title: str,
    row: dict,
    *,
    y: int,
    height: int,
    max_ops: float,
    headline: str,
    note: str,
) -> None:
    x = 10
    text(draw, title, x, y - 6, 16, bold=True, fill=TEAL)
    text(draw, headline, 288, y, 13, bold=True, fill=RED if "10/16" in headline else MUTED)
    text(draw, note, 812, y, 12, fill=MUTED)

    nodes = sorted(row["connection_graph"]["nodes"], key=lambda item: item["id"])
    traffic = {edge["source"]: edge["mb"] for edge in row["connection_graph"]["traffic_edges"]}
    gap = 6
    card_y = y + 30
    if len(nodes) == 9:
        card_w = 109
        start_x = 24
    else:
        card_w = 94
        start_x = 25
    card_h = height - 50
    for index, node in enumerate(nodes):
        chiplet_card(
            draw,
            start_x + index * (card_w + gap),
            card_y,
            card_w,
            card_h,
            node,
            max_ops,
            traffic.get(node["id"]),
        )


def chiplet_card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    node: dict,
    max_ops: float,
    traffic_mb: float | None,
) -> None:
    color = stage_color(node["stage"])
    draw.rounded_rectangle([x, y, x + w, y + h], radius=5, fill=SOFT, outline=LINE, width=1)
    draw.rounded_rectangle([x, y, x + w, y + 5], radius=3, fill=color)
    text(draw, f"C{node['id'] + 1}", x + 6, y + 14, 13, bold=True)
    wrapped(draw, node["stage"], x + 6, y + 35, w - 12, 11)
    out_label = "-" if traffic_mb is None else f"{traffic_mb:.2f} MB"
    text(draw, f"{node['ops'] / 1e9:.2f} GOP", x + 6, y + h - 35, 10, fill=MUTED)
    text(draw, f"out {out_label}", x + 6, y + h - 21, 9, fill=MUTED)
    bar(draw, x + 6, y + h - 8, w - 12, 4, node["ops"], max_ops, color)


def slide_title(draw: ImageDraw.ImageDraw, title: str, *, boxed: bool = False) -> None:
    if boxed:
        draw.rectangle([32, 10, 1033, 77], outline="#757575", width=1)
        text(draw, title, 44, 31, 33, fill=TITLE_BLUE, font_kind="title")
    else:
        text(draw, title, 47, 27, 34, fill=TITLE_BLUE, font_kind="title")
        draw.line([38, 83, 1036, 83], fill="#858585", width=1)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    network_motif(draw, 720, -15)
    network_motif(draw, -30, 501)
    return img, draw


def network_motif(draw: ImageDraw.ImageDraw, ox: int, oy: int) -> None:
    nodes = [
        (0, 38), (37, 56), (88, 38), (120, 73), (168, 46), (205, 69),
        (248, 26), (288, 60), (334, 36), (372, 72), (420, 43),
    ]
    for a, b in zip(nodes, nodes[1:]):
        draw.line([ox + a[0], oy + a[1], ox + b[0], oy + b[1]], fill="#dbe4ea", width=1)
    for x, y in nodes:
        px, py = ox + x, oy + y
        draw.ellipse([px - 10, py - 10, px + 10, py + 10], outline="#dbe4ea", width=1)
        draw.ellipse([px - 3, py - 3, px + 3, py + 3], fill="#cbd6dd")


def panel(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=6, fill=WHITE, outline=LINE, width=1)


def bar(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    w: float,
    h: float,
    value: float,
    maximum: float,
    fill: str,
) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill="#e7edf3")
    pct = 0.0 if maximum <= 0 else max(0.02, min(1.0, value / maximum))
    draw.rounded_rectangle([x, y, x + w * pct, y + h], radius=h / 2, fill=fill)


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
    lines: list[str] = []
    current = ""
    for word in value.split():
        test = word if not current else f"{current} {word}"
        if text_width(draw, test, font) <= max_w:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    for index, line in enumerate(lines[:4]):
        draw.text((x, y + index * int(size * 1.18)), line, font=font, fill=fill)


def text(
    draw: ImageDraw.ImageDraw,
    value: str,
    x: int,
    y: int,
    size: int,
    *,
    bold: bool = False,
    fill: str = INK,
    font_kind: str = "body",
) -> None:
    draw.text((x, y), value, font=font_for(size, bold=bold, kind=font_kind), fill=fill)


def text_width(draw: ImageDraw.ImageDraw, value: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), value, font=font)
    return bbox[2] - bbox[0]


def font_for(size: int, *, bold: bool = False, kind: str = "body") -> ImageFont.FreeTypeFont:
    if kind == "title":
        candidates = [Path("C:/Windows/Fonts/kaiu.ttf"), Path("C:/Windows/Fonts/msjh.ttc")]
    else:
        candidates = [
            Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/msjhbd.ttc" if bold else "C:/Windows/Fonts/msjh.ttc"),
            Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def read_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def goal_name(goal: str) -> str:
    return {
        "balanced": "Balanced",
        "latency": "Low latency",
        "power": "Low power",
        "area": "Low area",
    }[goal]


def stage_color(stage: str) -> str:
    if stage.startswith("conv1"):
        return BLUE
    if stage.startswith("stage2"):
        return GREEN
    if stage.startswith("stage3"):
        return ORANGE
    if stage.startswith("stage4"):
        return PURPLE
    if stage.startswith("conv5") or stage.endswith("fc"):
        return RED
    return TEAL


if __name__ == "__main__":
    main()
