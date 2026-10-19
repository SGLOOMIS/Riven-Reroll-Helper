"""Draw a fake reroll screen (two riven cards side by side) for testing OCR + parsing.

    python tests/make_sample.py tests/sample_rubico.png
"""

import sys

from PIL import Image, ImageDraw, ImageFont


def card(d, x, y, title, lines, font, title_font):
    d.rounded_rectangle([x - 30, y - 90, x + 330, y + 420], radius=16, fill=(38, 22, 60), outline=(170, 120, 230), width=3)
    d.text((x, y - 60), title, font=title_font, fill=(235, 220, 255))
    d.text((x + 60, y - 20), "RIVEN MOD", font=font, fill=(150, 130, 190))
    ty = y + 160
    for line in lines:
        for part in line.split("\n"):
            d.text((x, ty), part, font=font, fill=(240, 235, 255))
            ty += 30
        ty += 10


def main(out, kind="rubico"):
    img = Image.new("RGB", (1920, 1080), (12, 10, 18))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("segoeui.ttf", 22)
    title_font = ImageFont.truetype("segoeuib.ttf", 26)
    d.text((780, 60), "CYCLE RIVEN", font=title_font, fill=(220, 220, 220))
    if kind == "rubico":
        # Rubico, D=0.95, rank 8. Left: 3 pos + 1 neg. Right: 2 pos + 1 neg.
        card(d, 560, 250, "Rubico Critatox", ["+112.2% Critical Damage", "+80.2% Multishot",
                                              "+126.9% Critical Chance", "-42.7% Zoom"], font, title_font)
        card(d, 1100, 250, "Rubico Visi-acrinent", ["+180.4% Damage", "x1.58 Damage to Grineer",
                                                    "-56.4% Impact"], font, title_font)
    else:
        # Nikana (melee), rank 0, slide-crit stat that wraps onto two lines.
        card(d, 560, 250, "Nikana Crita-satilis", ["+7.7% Critical Damage",
                                                   "+9.7% Critical Chance on\nSlide Attack", "+12.4% Melee Damage"],
             font, title_font)
        card(d, 1100, 250, "Nikana Toxi-hexacron", ["+8.9% Toxin", "+0.2 Range", "+8.0% Status Chance",
                                                    "-13.0% Melee Damage"], font, title_font)
    img.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "rubico")
