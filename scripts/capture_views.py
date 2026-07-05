"""
Capture screenshots of the CapsWriter Desktop Tauri app window.
Uses win32gui to find and capture the window precisely.
"""
import sys
import os
import time

SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

try:
    import win32gui
    import win32ui
    import win32con
    import win32process
except ImportError:
    print("Installing pywin32...")
    os.system(f"{sys.executable} -m pip install pywin32 -q")
    import win32gui
    import win32ui
    import win32con
    import win32process

try:
    from PIL import Image
except ImportError:
    print("Installing Pillow...")
    os.system(f"{sys.executable} -m pip install Pillow -q")
    from PIL import Image


def find_tauri_windows(pid):
    """Find all window handles belonging to a given PID."""
    windows = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid == pid:
                title = win32gui.GetWindowText(hwnd)
                rect = win32gui.GetWindowRect(hwnd)
                class_name = win32gui.GetClassName(hwnd)
                windows.append((hwnd, title, rect, class_name))
        return True

    win32gui.EnumWindows(callback, None)
    return windows


def capture_window(hwnd, filepath):
    """Capture a window's content to a PNG file."""
    # Get window rect
    rect = win32gui.GetWindowRect(hwnd)
    x, y, x2, y2 = rect
    w = x2 - x
    h = y2 - y

    if w < 100 or h < 100:
        print(f"  Window too small ({w}x{h}), skipping")
        return False

    print(f"  Capturing window {w}x{h} at ({x},{y})")

    # Create device contexts
    hwndDC = win32gui.GetWindowDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()

    # Create bitmap
    saveBitMap = win32ui.CreateBitmap()
    saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
    saveDC.SelectObject(saveBitMap)

    # Use PrintWindow with PW_RENDERFULLCONTENT (0x00000002) for better capture
    result = win32gui.SendMessage(hwnd, win32con.WM_PRINT, saveDC.GetSafeHdc(), 
                                   win32con.PRF_CLIENT | win32con.PRF_CHILDREN | 0x00000002)

    # Convert to PIL Image
    bmpinfo = saveBitMap.GetInfo()
    bmpstr = saveBitMap.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRX", 0, 1)

    # Save
    img.save(filepath, "PNG")
    print(f"  Saved: {filepath}")

    # Cleanup
    win32gui.DeleteObject(saveBitMap.GetHandle())
    saveDC.DeleteDC()
    mfcDC.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwndDC)

    return True


def find_caps_writer_pid():
    """Find the caps-writer-desktop process ID."""
    import subprocess
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq caps-writer-desktop.exe", "/FO", "CSV", "/NH"],
                          capture_output=True, text=True)
    for line in result.stdout.strip().split("\n"):
        if "caps-writer-desktop" in line.lower():
            parts = line.split(",")
            if len(parts) >= 2:
                pid = int(parts[1].strip('"'))
                return pid
    return None


def main():
    pid = find_caps_writer_pid()
    if not pid:
        print("ERROR: CapsWriter Desktop not running")
        return

    print(f"Found CapsWriter Desktop PID: {pid}")

    windows = find_tauri_windows(pid)
    print(f"\nFound {len(windows)} windows for PID {pid}:")
    for hwnd, title, rect, cls in windows:
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        print(f"  hwnd={hwnd} title='{title}' class='{cls}' size={w}x{h}")

    # Find the largest visible window (the main app window)
    best_hwnd = None
    best_area = 0
    for hwnd, title, rect, cls in windows:
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        area = w * h
        if area > best_area and w > 100 and h > 100:
            best_area = area
            best_hwnd = hwnd

    if not best_hwnd:
        print("ERROR: Could not find a suitable window to capture")
        return

    # Bring window to front
    print(f"\nFocusing window hwnd={best_hwnd}")
    try:
        win32gui.ShowWindow(best_hwnd, 9)  # SW_RESTORE
        time.sleep(0.3)
        win32gui.SetForegroundWindow(best_hwnd)
        time.sleep(0.5)
    except Exception as e:
        print(f"  Warning: {e}")

    # Capture the main view (record view)
    print("\n--- Capturing Record View ---")
    filepath = os.path.join(SCREENSHOTS_DIR, "main-record-view.png")
    capture_window(best_hwnd, filepath)

    print(f"\nDone! Screenshots saved to: {SCREENSHOTS_DIR}")


if __name__ == "__main__":
    main()
