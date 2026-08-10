#!/usr/bin/env python3
"""Generate the Interactive Video Player icon at hicolor sizes."""
import math, os
from PIL import Image, ImageDraw, ImageFilter

S = 1024                      # supersampled master size
OUT = "packaging/icons"
os.makedirs(OUT, exist_ok=True)

# ---- palette ---------------------------------------------------------------
TOP    = (23, 37, 84)         # deep indigo
BOT    = (13, 110, 120)       # teal
PLAY   = (255, 255, 255)
WAVE   = (250, 190, 60)       # amber sensor beam
SHADOW = (0, 0, 0, 70)

img  = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d    = ImageDraw.Draw(img)

# ---- background: rounded square with vertical gradient ---------------------
grad = Image.new("RGB", (1, S))
gd   = ImageDraw.Draw(grad)
for y in range(S):
    t = y / (S - 1)
    gd.point((0, y), fill=tuple(int(TOP[i] + (BOT[i] - TOP[i]) * t) for i in range(3)))
grad = grad.resize((S, S))

mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
img.paste(grad, (0, 0), mask)

# soft top-left sheen (blurred so there is no visible band edge)
gloss = Image.new("L", (S, S), 0)
ImageDraw.Draw(gloss).ellipse(
    [int(-S * 0.35), int(-S * 0.55), int(S * 0.95), int(S * 0.42)], fill=46)
gloss = gloss.filter(ImageFilter.GaussianBlur(S * 0.09))
sheen = Image.new("RGBA", (S, S), (255, 255, 255, 255))
sheen.putalpha(Image.composite(gloss, Image.new("L", (S, S), 0), mask))
img.alpha_composite(sheen)

# ---- motion-sensor beam: three concentric arcs, upper-left ----------------
cx, cy = int(S * 0.245), int(S * 0.320)
for i, r in enumerate((0.110, 0.168, 0.226)):
    rad = int(S * r)
    d.arc([cx - rad, cy - rad, cx + rad, cy + rad], start=-56, end=56,
          fill=WAVE + (255 - i * 50,), width=int(S * 0.034))
# emitter dot
dot = int(S * 0.034)
d.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=WAVE)

# ---- play triangle, lower-right, with soft drop shadow --------------------
pcx, pcy = int(S * 0.605), int(S * 0.640)
R = int(S * 0.205)
tri = [(pcx + R * math.cos(math.radians(a)), pcy + R * math.sin(math.radians(a)))
       for a in (-90, 30, 150)]
# rotate so it points right
tri = [(pcx + (x - pcx) * math.cos(math.radians(90)) - (y - pcy) * math.sin(math.radians(90)),
        pcy + (x - pcx) * math.sin(math.radians(90)) + (y - pcy) * math.cos(math.radians(90)))
       for x, y in tri]

sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sh).polygon([(x + S * 0.010, y + S * 0.016) for x, y in tri], fill=SHADOW)
sh = sh.filter(ImageFilter.GaussianBlur(S * 0.018))
img.alpha_composite(Image.composite(sh, Image.new("RGBA", (S, S), (0, 0, 0, 0)), mask))
d = ImageDraw.Draw(img)
d.polygon(tri, fill=PLAY)

# ---- export ----------------------------------------------------------------
img.save(f"{OUT}/icon-master.png")
for sz in (16, 22, 24, 32, 48, 64, 128, 256):
    img.resize((sz, sz), Image.LANCZOS).save(f"{OUT}/motion-player-{sz}.png", optimize=True)
    print(f"  {sz:>3}px  {os.path.getsize(f'{OUT}/motion-player-{sz}.png'):>6} bytes")
print("total base64 ~",
      sum(os.path.getsize(f"{OUT}/motion-player-{s}.png")
          for s in (16, 22, 24, 32, 48, 64, 128, 256)) * 4 // 3, "chars")
