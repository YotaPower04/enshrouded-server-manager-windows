"""Render a mockup PNG of the dark-navy themed manager + first-run overlay.
Output: assets/theme_preview.png  (gitignored). Not part of the app."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Palette — must match THEME_* in src/enshrouded_manager.py
BG, HDR, ACC = "#0f0f1a", "#1a1a2e", "#00d4ff"
TXT, DIM = "#e8e8e8", "#888888"
BTN, HOVR, FIELD = "#1e3a5f", "#2a5080", "#12121e"
OK, ERR, WARN = "#27ae60", "#c0392b", "#e67e22"

F = "C:/Windows/Fonts/segoeui.ttf"
FB = "C:/Windows/Fonts/segoeuib.ttf"
def font(path, sz): return ImageFont.truetype(path, sz)

f_title  = font(FB, 30)
f_h      = font(FB, 17)
f_tab    = font(F, 15)
f_body   = font(F, 14)
f_small  = font(F, 12)
f_cap    = font(F, 13)

PW, PH, GAP = 680, 780, 40
img = Image.new("RGB", (PW * 2 + GAP, PH), "#05050a")
d = ImageDraw.Draw(img)

def rr(box, r, fill, outline=None, w=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=w)

def ctext(cx, y, s, fnt, fill):
    bb = d.textbbox((0, 0), s, font=fnt)
    d.text((cx - (bb[2] - bb[0]) / 2, y), s, font=fnt, fill=fill)

# ---- Panel A: First-Time Setup overlay -----------------------------------
ax = 0
rr((ax, 0, ax + PW, PH), 0, BG)
cx = ax + PW / 2
ctext(cx, 230, "First-Time Setup", f_title, ACC)
status = ["The server is generating your world for the",
          "first time. This can take several minutes —",
          "please wait…"]
for i, line in enumerate(status):
    ctext(cx, 300 + i * 26, line, f_h, TXT)
# busy bar
bw = 320
rr((cx - bw/2, 410, cx + bw/2, 420), 5, FIELD)
rr((cx - bw/2, 410, cx - bw/2 + 120, 420), 5, ACC)  # indeterminate chunk
ctext(cx, PH - 40, "First-run overlay", f_cap, DIM)

# ---- Panel B: Server Manager (Server tab) --------------------------------
bx = PW + GAP
rr((bx, 0, bx + PW, PH), 0, BG)
# tab bar
tabs = ["Server", "Logs", "Resource Server", "Worlds", "Configuration"]
tx = bx + 16
ty = 18
for i, t in enumerate(tabs):
    bb = d.textbbox((0, 0), t, font=f_tab)
    tw = bb[2] - bb[0] + 32
    sel = (i == 0)
    rr((tx, ty, tx + tw, ty + 38), 4, BG if sel else HDR)
    d.text((tx + 16, ty + 9), t, font=f_tab, fill=ACC if sel else DIM)
    tx += tw + 3
# pane
rr((bx + 16, ty + 38, bx + PW - 16, PH - 56), 6, BG, outline=HDR, w=1)
inx = bx + 40
iny = ty + 70
# status row
d.ellipse((inx, iny + 4, inx + 18, iny + 22), fill=OK)
d.text((inx + 30, iny), "Running", font=f_h, fill=TXT)
d.text((inx + 30, iny + 26), "Uptime  2h 14m", font=f_small, fill=DIM)
# group box: Server Info
gy = iny + 64
gw = PW - 80
rr((inx, gy, inx + gw, gy + 210), 6, BG, outline=HDR, w=1)
d.rectangle((inx + 12, gy - 8, inx + 120, gy + 8), fill=BG)
d.text((inx + 18, gy - 10), "Server Info", font=f_h, fill=ACC)
rows = [("Name", "Yota's World"), ("Players", "3 / 16"),
        ("Game Port", "15636 / UDP"), ("World", "world_1"),
        ("Version", "Enshrouded 0.9.0")]
for i, (k, v) in enumerate(rows):
    ry = gy + 24 + i * 34
    d.text((inx + 22, ry), k, font=f_body, fill=DIM)
    rr((inx + 180, ry - 4, inx + gw - 22, ry + 24), 4, FIELD)
    d.text((inx + 192, ry), v, font=f_body, fill=TXT)
# action buttons
byy = gy + 240
for i, (label, col) in enumerate([("Start", OK), ("Stop", ERR), ("Restart", WARN)]):
    bxx = inx + i * 150
    rr((bxx, byy, bxx + 134, byy + 40), 4, col)
    ctext(bxx + 67, byy + 11, label, f_h, "#ffffff")
# a secondary (default themed) button
rr((inx, byy + 56, inx + 200, byy + 92), 4, BTN)
ctext(inx + 100, byy + 65, "Open Save Folder", f_body, TXT)
ctext(bx + PW / 2, PH - 40, "Server Manager — Server tab", f_cap, DIM)

out = Path(__file__).resolve().parent.parent / "assets" / "theme_preview.png"
img.save(out)
print(f"saved {out}")
