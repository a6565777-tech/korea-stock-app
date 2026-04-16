"""앱 아이콘 생성 (PIL). 나중에 사용자가 이미지 바꾸면 이 파일은 삭제해도 됨."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

OUT = Path(__file__).parent / "icons"
OUT.mkdir(exist_ok=True)

# 짙은 네이비 배경 + 큰 📈 이모지 + "주식" 텍스트
def make(size: int, maskable: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), (10, 14, 26, 255))
    draw = ImageDraw.Draw(img)

    # maskable은 safe zone 고려해서 로고를 작게 그림
    pad = int(size * 0.18) if maskable else int(size * 0.08)
    logo_size = size - pad * 2

    # 차트 선 (단순 꺾은선)
    line_color = (74, 158, 255, 255)  # accent blue
    points = [
        (pad + logo_size * 0.1, pad + logo_size * 0.75),
        (pad + logo_size * 0.3, pad + logo_size * 0.55),
        (pad + logo_size * 0.5, pad + logo_size * 0.65),
        (pad + logo_size * 0.7, pad + logo_size * 0.35),
        (pad + logo_size * 0.9, pad + logo_size * 0.20),
    ]
    line_w = max(3, size // 40)
    for i in range(len(points) - 1):
        draw.line([points[i], points[i + 1]], fill=line_color, width=line_w)

    # 마지막 점에 원 (상승 강조)
    r = max(6, size // 24)
    last = points[-1]
    draw.ellipse((last[0] - r, last[1] - r, last[0] + r, last[1] + r), fill=(61, 214, 140, 255))

    # 작은 상승 화살표 ▲
    arrow_pts = [
        (pad + logo_size * 0.45, pad + logo_size * 0.92),
        (pad + logo_size * 0.55, pad + logo_size * 0.92),
        (pad + logo_size * 0.50, pad + logo_size * 0.85),
    ]
    draw.polygon(arrow_pts, fill=(61, 214, 140, 255))

    return img


for s in [192, 512]:
    img = make(s, maskable=False)
    img.save(OUT / f"icon-{s}.png")
    print(f"icon-{s}.png 생성")

img = make(512, maskable=True)
img.save(OUT / "icon-maskable-512.png")
print("icon-maskable-512.png 생성")
