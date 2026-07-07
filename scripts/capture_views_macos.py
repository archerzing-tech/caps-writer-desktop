#!/usr/bin/env python3
"""
Capture CapsWriter Desktop app window screenshots on macOS.
Uses screencapture -R with coordinate-based sidebar navigation.
"""
import os, re, time, subprocess, tempfile

SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


def applescript(script):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.applescript', delete=False) as f:
        f.write(script)
        tmppath = f.name
    try:
        r = subprocess.run(["osascript", tmppath], capture_output=True, text=True, timeout=15)
        return r.stdout.strip(), r.stderr.strip()
    finally:
        os.unlink(tmppath)


def get_window_bounds():
    out, err = applescript('''
tell application "System Events"
    set procs to every process whose name contains "caps-writer-des"
    if procs is {} then return "NF"
    set w to window 1 of item 1 of procs
    set p to position of w
    set s to size of w
    do shell script "echo " & (item 1 of p) & " " & (item 2 of p) & " " & (item 1 of s) & " " & (item 2 of s)
end tell
''')
    if err: print(f"  AS err: {err}")
    if not out or "NF" in out: return None
    nums = re.findall(r'\d+', out)
    if len(nums) >= 4: return int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3])
    return None


def focus_app(x, y, w, h):
    """Ensure the app window is focused. Click titlebar center, then wait."""
    # Click the titlebar to ensure window focus
    titlebar_cx = x + w // 2
    titlebar_cy = y + 14  # half of ~28px macOS native titlebar height
    subprocess.run(["cliclick", f"c:{titlebar_cx},{titlebar_cy}"], timeout=5)
    time.sleep(0.3)
    # Bring to front via AppleScript too
    applescript('''
tell application "System Events"
    set procs to every process whose name contains "caps-writer-des"
    if procs is {} then return
    set frontmost of (item 1 of procs) to true
end tell
''')
    time.sleep(0.3)


def click_at(cx, cy, label=""):
    """Click at screen coordinates and verify position."""
    subprocess.run(["cliclick", f"c:{cx},{cy}"], timeout=5)
    if label:
        print(f"    clicked {label}")


def capture(x, y, w, h, filepath):
    rect = f"{x},{y},{w},{h}"
    subprocess.run(["screencapture", "-R", rect, "-x", "-t", "png", filepath], capture_output=True, timeout=10)
    return os.path.getsize(filepath) if os.path.exists(filepath) else 0


def main():
    # Activate app
    applescript('''
tell application "System Events"
    set procs to every process whose name contains "caps-writer-des"
    if procs is {} then return
    set frontmost of (item 1 of procs) to true
end tell
''')
    time.sleep(1)

    bounds = get_window_bounds()
    if not bounds:
        print("ERROR: Window not found")
        return
    x, y, w, h = bounds
    print(f"Window: {w}x{h} at ({x},{y})")

    focus_app(x, y, w, h)
    time.sleep(0.5)

    # Sidebar: 64px wide, center x = x + 32.
    # CSS: titlebar=44px, .sidebar-items padding=8px, .sidebar-item padding=10px+20px icon+3px gap+~12px label
    # Total per sidebar button: ~55px, gap=2px.
    # Centers from window top (y=content top):
    #   item 0: 44 + 8 + 27.5 = 79.5
    #   item 1: 79.5 + 57 = 136.5
    #   item 2: 136.5 + 57 = 193.5
    #   item 3: 193.5 + 57 = 250.5
    views = [
        ("record",     79),
        ("transcribe", 137),
        ("history",    194),
        ("settings",   251),
    ]

    sidebar_cx = x + 32

    for view_name, dy in views:
        print(f"\n--- {view_name} ---")
        focus_app(x, y, w, h)
        time.sleep(0.2)

        cy = y + dy
        print(f"  Clicking at ({sidebar_cx}, {cy})")
        click_at(sidebar_cx, cy, view_name)
        time.sleep(0.8)

        # Second click attempt just in case (slightly shifted)
        print(f"  Retry click at ({sidebar_cx}, {cy+3})")
        click_at(sidebar_cx, cy + 3, f"{view_name} retry")
        time.sleep(0.5)

        curr = get_window_bounds()
        if curr:
            cx, cy2, cw, ch = curr
            fp = os.path.join(SCREENSHOTS_DIR, f"view-{view_name}.png")
            sz = capture(cx, cy2, cw, ch, fp)
            print(f"  Saved: {os.path.basename(fp)} ({cw}x{ch}, {sz/1024:.1f} KB)")
        else:
            print(f"  Window lost")

    print(f"\nDone → {SCREENSHOTS_DIR}/")
    for vn, _ in views:
        fp = os.path.join(SCREENSHOTS_DIR, f"view-{vn}.png")
        if os.path.exists(fp):
            print(f"  ✓ view-{vn}.png ({os.path.getsize(fp)/1024:.1f} KB)")
        else:
            print(f"  ✗ view-{vn}.png MISSING")


if __name__ == "__main__":
    main()
