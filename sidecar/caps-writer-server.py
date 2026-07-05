#!/usr/bin/env python3
"""
CapsWriter Desktop ASR Server - Entry point for Tauri sidecar.

Called by Tauri as an external binary/sidecar process.
Starts a WebSocket server on port 6016 (or $CW_PORT).
"""

import sys
import os
import asyncio

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.server import main


if __name__ == '__main__':
    print("[CapsWriter-Desktop] Starting ASR sidecar...", flush=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[CapsWriter-Desktop] Shutting down...", flush=True)
    except Exception as e:
        print(f"[CapsWriter-Desktop] Fatal error: {e}", flush=True)
        sys.exit(1)
