#!/usr/bin/env python3
"""Tint Zuodong CC0 woodblock brushes to the map's sepia palette and resize.

Ink strength is derived from luminance so both black-on-transparent and
grey-on-white brushes tint correctly: rgb -> sepia, alpha -> alpha * (1-lum).
"""
import os
from PIL import Image

SRC = "/tmp/zuodong-png/Zuodong Cartography Brushes 2.0 PNG Pack"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "zuodong")
os.makedirs(OUT, exist_ok=True)
SEPIA = (88, 64, 36)
ALPHA_BOOST = 1.4

PICKS = {
    "m3": [("Landforms/Mountains/Mountain 001.png", 220),
           ("Landforms/Mountains/Mountain 003.png", 220),
           ("Landforms/Mountains/Mountain 005.png", 220)],
    "m2": [("Landforms/Mountains/Mountain 010.png", 170),
           ("Landforms/Mountains/Mountain 015.png", 170),
           ("Landforms/Mountains/Mountain 020.png", 170)],
    "m1": [("Landforms/Hills/Hill 002.png", 130),
           ("Landforms/Hills/Hill 003.png", 130),
           ("Landforms/Hills/Hill 006.png", 130)],
    "tree": [("Flora/Forests/Regular Forests/Forest 001.png", 150),
             ("Flora/Forests/Regular Forests/Forest 002.png", 150),
             ("Flora/Forests/Regular Forests/Forest 004.png", 150)],
    "wave": [("Waves/Waves 005.png", 170),
             ("Waves/Waves 012.png", 170)],
    "spot-city": [("Settlements/Cities/Huge Cities/Huge City 001.png", 120)],
    "spot-town": [("Settlements/Cities/Large Cities/Large City 002.png", 104)],
    "spot-fort": [("Settlements/Forts/Fort 002.png", 88)],
    "spot-hall": [("Settlements/Buildings/Building 003.png", 80)],
    "spot-hall2": [("Settlements/Buildings/Building 005.png", 84)],
    "spot-hall3": [("Settlements/Buildings/Building 006.png", 80)],
    "spot-hall4": [("Settlements/Buildings/Building 001.png", 80)],
    "spot-pagoda": [("Settlements/Pagodas/Pagoda 004.png", 60)],
    "spot-pagoda2": [("Settlements/Pagodas/Pagoda 006.png", 52)],
}

for key, items in PICKS.items():
    for i, (rel, width) in enumerate(items):
        im = Image.open(os.path.join(SRC, rel)).convert("RGBA")
        px = im.load()
        w, h = im.size
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
                na = min(255, int(a * (1.0 - lum) * ALPHA_BOOST))
                px[x, y] = (SEPIA[0], SEPIA[1], SEPIA[2], na)
        nh = max(1, round(h * width / w))
        im = im.resize((width, nh), Image.LANCZOS)
        name = f"{key}-{i}.png"
        im.save(os.path.join(OUT, name))
        print(f"{name}: {width}x{nh}  <- {rel}")
print("done ->", OUT)
