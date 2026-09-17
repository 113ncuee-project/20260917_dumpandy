from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "resnet50_15fps_shufflenet_v2_500fps" / "ppt_assets"
OUT.mkdir(parents=True, exist_ok=True)

WIDTH = 936
HEIGHT = 402

INK = "#1f2933"
MUTED = "#596673"
WHITE = "#ffffff"
SOFT = "#f8fbff"
LINE = "#dbe6f0"
BLUE = "#1677e8"
GREEN = "#13966f"
PURPLE = "#6a53d8"
ORANGE = "#f47713"


STAGES = [
    {
        "number": "1",
        "title": "Workload Input",
        "subtitle": "模型輸入",
        "color": BLUE,
        "points": ["模型與 Target FPS", "Stage MACs", "Feature size"],
    },
    {
        "number": "2",
        "title": "Candidate Search",
        "subtitle": "候選設計",
        "color": GREEN,
        "points": ["Chiplet 數量 1-16", "Mesh / Tree", "Stage partition"],
    },
    {
        "number": "3",
        "title": "RapidChiplet Eval.",
        "subtitle": "系統評估",
        "color": PURPLE,
        "points": ["Placement / Routing", "Traffic simulation", "Latency / Power / Area"],
    },
    {
        "number": "4",
        "title": "PPA Selection",
        "subtitle": "評分輸出",
        "color": ORANGE,
        "points": ["PPA score", "Best design", "CSV / HTML report"],
    },
]


def main() -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    draw_background(draw)

    card_w = 196
    card_h = 350
    gap = 40
    start_x = 8
    y = 31

    for index, stage in enumerate(STAGES):
        x = start_x + index * (card_w + gap)
        card(draw, x, y, card_w, card_h, stage)
        if index < len(STAGES) - 1:
            arrow(draw, x + card_w + 12, y + card_h / 2, x + card_w + gap - 12, y + card_h / 2)

    output = OUT / "11_simplified_architecture.png"
    img.save(output)
    print(f"Wrote {output}")


def draw_background(draw: ImageDraw.ImageDraw) -> None:
    for x, y in [(760, 12), (805, 33), (857, 18), (905, 45), (936, 24)]:
        draw.ellipse([x - 9, y - 9, x + 9, y + 9], outline="#dce7ee", width=1)
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill="#cbd8df")
    for a, b in [((760, 12), (805, 33)), ((805, 33), (857, 18)), ((857, 18), (905, 45)), ((905, 45), (936, 24))]:
        draw.line([*a, *b], fill="#dce7ee", width=1)


def card(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, stage: dict) -> None:
    color = stage["color"]
    draw.rounded_rectangle([x, y, x + w, y + h], radius=9, fill=WHITE, outline=color, width=2)
    draw.rounded_rectangle([x, y, x + w, y + 70], radius=9, fill=color)
    draw.rectangle([x, y + 60, x + w, y + 70], fill=color)

    draw.ellipse([x + 14, y + 15, x + 48, y + 49], outline=WHITE, width=2)
    centered(draw, stage["number"], x + 31, y + 32, 23, bold=True, fill=WHITE)
    text(draw, stage["title"], x + 58, y + 21, 15, bold=True, fill=WHITE)
    text(draw, stage["subtitle"], x + 58, y + 47, 12, fill="#eaf4ff")

    body_x = x + 16
    body_y = y + 100
    for i, point in enumerate(stage["points"]):
        bullet_y = body_y + i * 65
        draw.rounded_rectangle([body_x, bullet_y, x + w - 16, bullet_y + 47], radius=8, fill=SOFT, outline=LINE, width=1)
        draw.ellipse([body_x + 13, bullet_y + 19, body_x + 21, bullet_y + 27], fill=color)
        wrapped(draw, point, body_x + 32, bullet_y + 11, w - 66, 15, bold=True, fill=INK, max_lines=2)


def arrow(draw: ImageDraw.ImageDraw, x1: float, y1: float, x2: float, y2: float) -> None:
    draw.line([x1, y1, x2, y2], fill="#7b8794", width=4)
    draw.polygon([(x2, y2), (x2 - 11, y2 - 9), (x2 - 11, y2 + 9)], fill="#7b8794")


def text(draw: ImageDraw.ImageDraw, value: str, x: int, y: int, size: int, *, bold: bool = False, fill: str = INK) -> None:
    draw.text((x, y), value, font=font_for(size, bold=bold), fill=fill)


def centered(draw: ImageDraw.ImageDraw, value: str, x: float, y: float, size: int, *, bold: bool = False, fill: str = INK) -> None:
    font = font_for(size, bold=bold)
    bbox = draw.textbbox((0, 0), value, font=font)
    draw.text((x - (bbox[2] - bbox[0]) / 2, y - (bbox[3] - bbox[1]) / 2), value, font=font, fill=fill)


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
    max_lines: int = 2,
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
    for i, line in enumerate(lines[:max_lines]):
        draw.text((x, y + i * int(size * 1.15)), line, font=font, fill=fill)


def text_width(draw: ImageDraw.ImageDraw, value: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), value, font=font)
    return bbox[2] - bbox[0]


def font_for(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/msjhbd.ttc" if bold else "C:/Windows/Fonts/msjh.ttc"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


if __name__ == "__main__":
    main()
