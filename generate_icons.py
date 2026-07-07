#!/usr/bin/env python3
"""Generate CapsWriter Desktop app icons — v2 (enhanced design).

Design: rounded-rect blue gradient background, white microphone with
subtle drop-shadow, "CW" monogram badge, and audio-wave accents.

Output: all Tauri-required icon sizes in src-tauri/icons/
"""

import math
from PIL import Image, ImageDraw, ImageFont

# ── Design constants ──────────────────────────────────────────────
ICON_SIZE = 1024
# Gradient: top-left → bottom-right diagonal
GRAD_TL = (96, 165, 250)    # #60a5fa — blue-400
GRAD_BR = (30, 58, 138)     # #1e3a8a — blue-900
MIC_WHITE = (255, 255, 255, 255)
MIC_SHADOW = (0, 0, 0, 50)
ACCENT = (34, 197, 94)       # #22c55e — green-500 (small accent dot)
CORNER_R = 210
SHADOW_OFFSET = 12
SHADOW_BLUR_RADIUS = 30


def radial_shine(size, cx, cy, radius, intensity=40):
    """Create a subtle radial highlight for depth."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for r in range(radius, 0, -1):
        alpha = int(intensity * (r / radius) ** 2)
        d.ellipse(
            [(cx - r, cy - r), (cx + r, cy + r)],
            fill=(255, 255, 255, alpha),
        )
    return img


def gradient_bg_diag(size, tl, br):
    """Create a diagonal (top-left → bottom-right) gradient."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            r = int(tl[0] + (br[0] - tl[0]) * t)
            g = int(tl[1] + (br[1] - tl[1]) * t)
            b = int(tl[2] + (br[2] - tl[2]) * t)
            px[x, y] = (r, g, b, 255)
    return img


def rounded_rect_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=255)
    return mask


def draw_rounded_rect(draw, box, radius, fill):
    """Draw a filled rounded rectangle."""
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def draw_microphone_refined(draw, cx, cy, size):
    """Draw a clean, modern microphone icon.

    The microphone is a capsule-shaped body with horizontal grille lines,
    a U-shaped mounting bracket, stand, and base.
    """
    s = size  # shorthand

    # ── Capsule microphone body ──
    mic_w = int(s * 0.22)
    mic_h = int(s * 0.40)
    mic_r = mic_w // 2
    mic_x0 = cx - mic_w // 2
    mic_y0 = cy - mic_h // 2 - int(s * 0.04)
    mic_x1 = mic_x0 + mic_w
    mic_y1 = mic_y0 + mic_h

    # Main body fill
    draw.rounded_rectangle(
        [(mic_x0, mic_y0), (mic_x1, mic_y1)],
        radius=mic_r,
        fill=MIC_WHITE,
    )

    # Subtle inner shadow (darker center band for 3D feel)
    shadow_band_h = int(mic_h * 0.06)
    for i in range(3):
        yy = mic_y0 + mic_h // 2 - shadow_band_h + i * shadow_band_h
        alpha = 25 - i * 8
        draw.line(
            [(mic_x0 + 6, yy), (mic_x1 - 6, yy)],
            fill=(0, 0, 0, max(0, alpha)),
            width=2,
        )

    # Grille lines (subtle horizontal lines)
    grill_color = (200, 215, 240, 120)
    n_lines = 5
    gap = (mic_h - 20) // (n_lines + 1)
    for i in range(1, n_lines + 1):
        yy = mic_y0 + 10 + gap * i
        draw.line(
            [(mic_x0 + 12, yy), (mic_x1 - 12, yy)],
            fill=grill_color,
            width=3,
        )

    # ── U-shaped bracket ──
    bracket_w = int(s * 0.32)
    bracket_h = int(s * 0.16)
    bracket_x0 = cx - bracket_w // 2
    bracket_y0 = mic_y1 - int(s * 0.02)
    bracket_x1 = bracket_x0 + bracket_w
    bracket_y1 = bracket_y0 + bracket_h
    bracket_width = max(10, int(s * 0.014))
    draw.arc(
        [(bracket_x0, bracket_y0), (bracket_x1, bracket_y1)],
        start=0, end=180,
        fill=MIC_WHITE, width=bracket_width,
    )

    # ── Stand ──
    stand_w = max(8, int(s * 0.012))
    stand_top = bracket_y0 + bracket_h // 2 - int(s * 0.01)
    stand_bot = stand_top + int(s * 0.10)
    draw.rectangle(
        [(cx - stand_w // 2, stand_top), (cx + stand_w // 2, stand_bot)],
        fill=MIC_WHITE,
    )

    # ── Base ──
    base_w = int(s * 0.18)
    base_h = max(8, int(s * 0.012))
    base_x0 = cx - base_w // 2
    base_y0 = stand_bot - max(6, int(s * 0.006))
    draw.rounded_rectangle(
        [(base_x0, base_y0), (base_x0 + base_w, base_y0 + base_h)],
        radius=base_h // 2,
        fill=MIC_WHITE,
    )

    # ── Sound waves (right) ──
    wave_alpha = 160
    wave_color_r = (255, 255, 255, wave_alpha)
    wave_x = mic_x1 + int(s * 0.05)
    wave_cy = cy - int(s * 0.04)
    for arc_r in [int(s * 0.09), int(s * 0.14), int(s * 0.19)]:
        thickness = max(5, int(s * 0.010))
        draw.arc(
            [(wave_x, wave_cy - arc_r), (wave_x + arc_r * 2, wave_cy + arc_r)],
            start=315, end=45,
            fill=wave_color_r, width=thickness,
        )

    # ── Sound waves (left, mirrored) ──
    wave_x_l = mic_x0 - int(s * 0.05)
    for arc_r in [int(s * 0.09), int(s * 0.14), int(s * 0.19)]:
        thickness = max(5, int(s * 0.010))
        draw.arc(
            [(wave_x_l - arc_r * 2, wave_cy - arc_r), (wave_x_l, wave_cy + arc_r)],
            start=135, end=225,
            fill=wave_color_r, width=thickness,
        )


def draw_cw_badge(draw, cx, cy, size):
    """Draw a small 'CW' monogram badge in the bottom-right corner."""
    badge_size = int(size * 0.16)
    badge_x = cx + int(size * 0.32) - badge_size // 2
    badge_y = cy + int(size * 0.32) - badge_size // 2

    # Badge background (slightly brighter blue circle)
    badge_color = (255, 255, 255, 40)
    r = badge_size // 2
    draw.ellipse(
        [(badge_x - r, badge_y - r), (badge_x + r, badge_y + r)],
        fill=badge_color,
    )

    # "CW" text
    try:
        # Try system fonts for a clean look
        font_size = int(badge_size * 0.48)
        for font_name in [
            "/System/Library/Fonts/SFNSMono.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFNSDisplay.ttf",
            None,
        ]:
            try:
                font = ImageFont.truetype(font_name, font_size) if font_name else ImageFont.load_default()
                break
            except (OSError, IOError):
                continue
        else:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    text = "CW"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        (badge_x - tw // 2, badge_y - th // 2 - 2),
        text,
        fill=(255, 255, 255, 200),
        font=font,
    )


def create_icon():
    """Generate the master icon and save all required sizes."""
    S = ICON_SIZE

    # ── Background: diagonal gradient ──
    bg = gradient_bg_diag(S, GRAD_TL, GRAD_BR)

    # ── Subtle radial highlight (top-left, for depth) ──
    shine = radial_shine(S, int(S * 0.3), int(S * 0.25), int(S * 0.5), intensity=35)
    bg = Image.alpha_composite(bg, shine)

    # ── Apply rounded-rect mask ──
    mask = rounded_rect_mask(S, CORNER_R)
    bg.putalpha(mask)

    # ── Drop shadow (offset dark copy behind mic) ──
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    cx_s, cy_s = S // 2 + SHADOW_OFFSET, S // 2 - int(S * 0.02) + SHADOW_OFFSET
    draw_microphone_refined(sd, cx_s, cy_s, S)
    shadow = shadow.filter(__import__('PIL.ImageFilter', fromlist=['GaussianBlur']).GaussianBlur(SHADOW_BLUR_RADIUS))
    shadow.putalpha(Image.eval(shadow.split()[3], lambda a: min(a, 60)))
    bg = Image.alpha_composite(bg, shadow)

    # ── Draw main microphone ──
    draw = ImageDraw.Draw(bg)
    cx, cy = S // 2, S // 2 - int(S * 0.02)
    draw_microphone_refined(draw, cx, cy, S)

    # ── "CW" monogram badge ──
    draw_cw_badge(draw, cx, cy, S)

    # ── Small accent dot (subtle brand touch) ──
    dot_r = int(S * 0.018)
    dot_x = cx + int(S * 0.22)
    dot_y = cy - int(S * 0.18)
    draw.ellipse(
        [(dot_x - dot_r, dot_y - dot_r), (dot_x + dot_r, dot_y + dot_r)],
        fill=(*ACCENT, 200),
    )

    # ── Save master icon ──
    src_dir = "src-tauri/icons"
    master_path = f"{src_dir}/icon.png"
    bg.save(master_path, "PNG")
    print(f"Saved master icon: {master_path} (1024×1024)")

    # ── Generate required sizes ──
    sizes = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "Square44x44Logo.png": 44,
        "Square150x150Logo.png": 150,
        "StoreLogo.png": 50,
    }

    for filename, size in sizes.items():
        resized = bg.resize((size, size), Image.LANCZOS)
        path = f"{src_dir}/{filename}"
        resized.save(path, "PNG")
        print(f"  {filename} ({size}×{size})")

    # ── Generate .ico for Windows ──
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_images = [bg.resize(s, Image.LANCZOS) for s in ico_sizes]
    ico_path = f"{src_dir}/icon.ico"
    ico_images[0].save(
        ico_path, format="ICO",
        sizes=ico_sizes,
        append_images=ico_images[1:],
    )
    print(f"  icon.ico (multi-size)")

    # ── Generate .icns for macOS ──
    import subprocess, tempfile, os
    iconset = tempfile.mkdtemp(suffix=".iconset")
    icns_sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for name, sz in icns_sizes.items():
        bg.resize((sz, sz), Image.LANCZOS).save(os.path.join(iconset, name))
    icns_path = f"{src_dir}/icon.icns"
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns_path], check=True)
    print(f"  icon.icns (macOS)")

    print(f"\nAll icons generated → {src_dir}/")


if __name__ == "__main__":
    create_icon()
