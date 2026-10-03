"""生成用于 Typography / OCR 真实视频验收的最小样本。"""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUTPUT = Path(__file__).parent.parent / "samples" / "test_typography.mp4"
WIDTH = 1280
HEIGHT = 720
FPS = 24
DURATION = 5.0


def _load_font(size: int = 72) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/yu Gothic.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _frame_at(time: float, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> np.ndarray:
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)

    # 0-1s: 静态英文 "SUMMER"
    if 0.0 <= time < 1.0:
        bbox = draw.textbbox((0, 0), "SUMMER", font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (WIDTH - text_w) // 2
        y = (HEIGHT - text_h) // 2
        draw.text((x, y), "SUMMER", fill=(20, 20, 20), font=font)

    # 1-2s: 移动文字 "MOTION"
    elif 1.0 <= time < 2.0:
        t = time - 1.0
        bbox = draw.textbbox((0, 0), "MOTION", font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = int((WIDTH - text_w) * t)
        y = (HEIGHT - text_h) // 2
        draw.text((x, y), "MOTION", fill=(50, 50, 180), font=font)

    # 2-3s: 静态 "FADE"
    elif 2.0 <= time < 3.0:
        bbox = draw.textbbox((0, 0), "FADE", font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        alpha = int(255 * min(1.0, (time - 2.0) / 0.5))
        color = (alpha, alpha, alpha)
        x = (WIDTH - text_w) // 2
        y = (HEIGHT - text_h) // 2
        draw.text((x, y), "FADE", fill=color, font=font)

    # 3-5s: 两段不同文字
    else:
        bbox1 = draw.textbbox((0, 0), "TITLE", font=font)
        bw1 = bbox1[2] - bbox1[0]
        bh1 = bbox1[3] - bbox1[1]
        draw.text((100, 100), "TITLE", fill=(180, 30, 30), font=font)

        bbox2 = draw.textbbox((0, 0), "LYRICS", font=font)
        bw2 = bbox2[2] - bbox2[0]
        draw.text((WIDTH - bw2 - 100, HEIGHT - bh1 - 100), "LYRICS", fill=(30, 30, 30), font=font)

    return np.array(img)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    font = _load_font(96)

    container = av.open(str(OUTPUT), mode="w")
    stream = container.add_stream("libx264", rate=FPS)
    stream.width = WIDTH
    stream.height = HEIGHT
    stream.pix_fmt = "yuv420p"

    frame_count = int(DURATION * FPS)
    for i in range(frame_count):
        t = i / FPS
        image = _frame_at(t, font)
        frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)

    for packet in stream.encode():
        container.mux(packet)
    container.close()
    print(f"Generated {OUTPUT}")


if __name__ == "__main__":
    main()
