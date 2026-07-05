"""
Navigate the CapsWriter Desktop app to each view and capture screenshots.
Uses win32gui/win32api to simulate mouse clicks on sidebar buttons.
"""
import os
import sys
import time

try:
    import win32gui
    import win32api
    import win32con
    import win32process
except ImportError:
    os.system(f"{sys.executable} -m pip install pywin32 -q")
    import win32gui
    import win32api
    import win32con
    import win32process

try:
    from PIL import Image
except ImportError:
    os.system(f"{sys.executable} -m pip install Pillow -q")
    from PIL import Image

SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "screenshots")


def find_caps_writer_pid():
    import subprocess
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq caps-writer-desktop.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True
    )
    for line in result.stdout.strip().split("\n"):
        if "caps-writer-desktop" in line.lower():
            parts = line.split(",")
            if len(parts) >= 2:
                return int(parts[1].strip('"'))
    return None


def find_tauri_window(pid):
    """Find the main Tauri window (largest visible window for the process)."""
    result = {"hwnd": None, "rect": None, "area": 0}

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid == pid:
                rect = win32gui.GetWindowRect(hwnd)
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                area = w * h
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
                print(f"  hwnd={hwnd} title='{title}' class='{cls}' size={w}x{h} area={area}")
                if area > result["area"]:
                    result["area"] = area
                    result["hwnd"] = hwnd
                    result["rect"] = rect
        return True

    win32gui.EnumWindows(callback, None)
    return result


def capture_screen_region(x, y, w, h, filepath):
    """Capture a specific region of the screen."""
    bitmap = Image.new("RGB", (w, h))
    # Use mss for faster screen capture
    try:
        import mss
        with mss.mss() as sct:
            monitor = {"left": x, "top": y, "width": w, "height": h}
            screenshot = sct.grab(monitor)
            bitmap = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
    except ImportError:
        # Fallback to win32
        import win32ui
        hwndDC = win32gui.GetDC(0)
        mfcDC = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
        saveDC.SelectObject(saveBitMap)
        saveDC.BitBlt((0, 0), (w, h), mfcDC, (x, y), win32con.SRCCOPY)
        bmpinfo = saveBitMap.GetInfo()
        bmpstr = saveBitMap.GetBitmapBits(True)
        bitmap = Image.frombuffer("RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRX", 0, 1)
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(0, hwndDC)

    bitmap.save(filepath, "PNG")
    size = os.path.getsize(filepath)
    print(f"  Saved: {filepath} ({w}x{h}, {size} bytes)")
    return filepath


def click_at(x, y):
    """Simulate a mouse click at screen coordinates."""
    win32api.SetCursorPos((x, y))
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    time.sleep(0.02)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    time.sleep(0.3)


def main():
    pid = find_caps_writer_pid()
    if not pid:
        print("ERROR: CapsWriter Desktop not running")
        return

    print(f"Found CapsWriter Desktop PID: {pid}")

    # Find the main window
    win_info = find_tauri_window(pid)
    if not win_info["hwnd"]:
        print("ERROR: Could not find window")
        return

    hwnd = win_info["hwnd"]
    rect = win_info["rect"]
    win_x, win_y = rect[0], rect[1]
    win_w = rect[2] - rect[0]
    win_h = rect[3] - rect[1]
    print(f"\nMain window: {win_w}x{win_h} at ({win_x},{win_y})")

    # Bring to front
    try:
        win32gui.ShowWindow(hwnd, 9)
        time.sleep(0.2)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.5)
    except Exception as e:
        print(f"  Warning bringing to front: {e}")

    # Get actual position after bringing to front
    new_rect = win32gui.GetWindowRect(hwnd)
    win_x, win_y = new_rect[0], new_rect[1]
    win_w = new_rect[2] - new_rect[0]
    win_h = new_rect[3] - new_rect[1]
    print(f"Window after focus: {win_w}x{win_h} at ({win_x},{win_y})")

    # Sidebar button positions (relative to window):
    # Sidebar width = 64px, buttons start after titlebar (44px)
    # Each button is roughly 50px tall
    sidebar_center_x = win_x + 32  # center of 64px sidebar

    # Button Y positions (approximate, relative to window top):
    # Record:     ~44 + 10 + 24 = 78
    # Transcribe: ~44 + 10 + 50 + 50 = 154
    # History:    ~44 + 10 + 50 + 50 + 50 = 204
    # Settings:   ~44 + 10 + 50 + 50 + 50 + 50 = 254
    views = [
        ("view-record",     sidebar_center_x, win_y + 78),
        ("view-transcribe", sidebar_center_x, win_y + 128),
        ("view-history",    sidebar_center_x, win_y + 178),
        ("view-settings",   sidebar_center_x, win_y + 228),
    ]

    # If window is too small (Tauri HWND issue), use full-screen crop approach
    if win_w < 200 or win_h < 200:
        print("\nWindow too small, using full-screen approach...")
        # Use the fullscreen.png we already captured
        fs_path = os.path.join(SCREENSHOTS_DIR, "fullscreen.png")
        if os.path.exists(fs_path):
            img = Image.open(fs_path)
            fw, fh = img.size
            print(f"Full screen: {fw}x{fh}")

            # Use tauri.conf.json window config: 800x660 centered
            app_w, app_h = 800, 660
            cx = (fw - app_w) // 2
            cy = (fh - app_h) // 2

            # The record view is already captured
            record_path = os.path.join(SCREENSHOTS_DIR, "view-record.png")
            if not os.path.exists(record_path) or os.path.getsize(record_path) < 10000:
                cropped = img.crop((cx, cy, cx + app_w, cy + app_h))
                cropped.save(record_path, "PNG")
                print(f"  Record view: {record_path}")

            # For other views, we need to navigate the app
            # Try clicking sidebar buttons using screen coordinates
            sidebar_cx = cx + 32
            button_ys = [cy + 78, cy + 128, cy + 178, cy + 228]
            view_names = ["view-record", "view-transcribe", "view-history", "view-settings"]

            for name, bx, by in zip(view_names, [sidebar_cx]*4, button_ys):
                print(f"\nNavigating to {name}...")
                click_at(bx, by)
                time.sleep(0.8)

                # Re-read window rect in case it moved
                try:
                    new_rect = win32gui.GetWindowRect(hwnd)
                    wx, wy = new_rect[0], new_rect[1]
                    ww, wh = new_rect[2] - new_rect[0], new_rect[3] - new_rect[1]
                    if ww > 200 and wh > 200:
                        filepath = os.path.join(SCREENSHOTS_DIR, f"{name}.png")
                        capture_screen_region(wx, wy, ww, wh, filepath)
                    else:
                        # Use full-screen crop
                        filepath = os.path.join(SCREENSHOTS_DIR, f"{name}.png")
                        cropped = img.crop((cx, cy, cx + app_w, cy + app_h))
                        cropped.save(filepath, "PNG")
                        print(f"  Cropped from fullscreen: {filepath}")
                except Exception as e:
                    print(f"  Error: {e}")

            img.close()
        return

    # If window is large enough, capture directly
    for name, btn_x, btn_y in views:
        print(f"\nNavigating to {name}...")
        click_at(btn_x, btn_y)
        time.sleep(0.8)

        # Re-get window position
        try:
            r = win32gui.GetWindowRect(hwnd)
            wx, wy = r[0], r[1]
            ww, wh = r[2] - r[0], r[3] - r[1]
            filepath = os.path.join(SCREENSHOTS_DIR, f"{name}.png")
            capture_screen_region(wx, wy, ww, wh, filepath)
        except Exception as e:
            print(f"  Error: {e}")


if __name__ == "__main__":
    main()
