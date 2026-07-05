"""
Crop the CapsWriter Desktop window from the full-screen screenshot.
On a 3440x1440 screen with an 800x660 centered window:
  x = (3440-800)/2 = 1320, y = (1440-660)/2 = 390
"""
import os
import sys

try:
    from PIL import Image
except ImportError:
    os.system(f"{sys.executable} -m pip install Pillow -q")
    from PIL import Image

SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "screenshots")
fullscreen_path = os.path.join(SCREENSHOTS_DIR, "fullscreen.png")

if not os.path.exists(fullscreen_path):
    print(f"ERROR: {fullscreen_path} not found")
    sys.exit(1)

img = Image.open(fullscreen_path)
w, h = img.size
print(f"Full screen: {w}x{h}")

# The CapsWriter window config: width=800, height=660, center=true
app_w, app_h = 800, 660
x = (w - app_w) // 2
y = (h - app_h) // 2

print(f"Cropping: x={x} y={y} w={app_w} h={app_h}")
cropped = img.crop((x, y, x + app_w, y + app_h))
output = os.path.join(SCREENSHOTS_DIR, "view-record.png")
cropped.save(output, "PNG")
print(f"Saved: {output} ({app_w}x{app_h})")

img.close()
cropped.close()
