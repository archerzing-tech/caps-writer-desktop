#!/usr/bin/env python3
"""Generate placeholder icons for CapsWriter Desktop Tauri app."""
import struct
import zlib
import os

def create_png(width, height, r, g, b, filename):
    """Create a simple solid-color PNG."""
    # PNG signature
    signature = b'\x89PNG\r\n\x1a\n'
    
    # IHDR chunk
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
    ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
    
    # IDAT chunk - image data
    raw_data = b''
    for y in range(height):
        raw_data += b'\x00'  # filter byte
        for x in range(width):
            raw_data += bytes([r, g, b])
    
    compressed = zlib.compress(raw_data)
    idat_crc = zlib.crc32(b'IDAT' + compressed) & 0xffffffff
    idat = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc)
    
    # IEND chunk
    iend_crc = zlib.crc32(b'IEND') & 0xffffffff
    iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
    
    # ICO header (for .ico)
    if filename.endswith('.ico'):
        # Create ICO file with embedded PNG
        png_data = signature + ihdr + idat + iend
        ico_header = struct.pack('<HHH', 0, 1, 1)  # reserved, type=1 (icon), count=1
        ico_entry = struct.pack('<BBBBHHII', 
            width if width < 256 else 0,
            height if height < 256 else 0,
            0, 0,  # colors, reserved
            1, 32,  # planes, bpp
            len(png_data),  # size
            22  # offset (6 + 16)
        )
        with open(filename, 'wb') as f:
            f.write(ico_header + ico_entry + png_data)
        return
    
    # Regular PNG
    with open(filename, 'wb') as f:
        f.write(signature + ihdr + idat + iend)

def main():
    icons_dir = os.path.join(os.path.dirname(__file__), '..', 'src-tauri', 'icons')
    os.makedirs(icons_dir, exist_ok=True)
    
    # Color: teal/green (#00b894)
    r, g, b = 0, 184, 148
    
    icons = [
        ('32x32.png', 32, 32),
        ('128x128.png', 128, 128),
        ('128x128@2x.png', 256, 256),
        ('icon.ico', 32, 32),
    ]
    
    for name, w, h in icons:
        path = os.path.join(icons_dir, name)
        create_png(w, h, r, g, b, path)
        print(f"Created: {path}")

if __name__ == '__main__':
    main()
