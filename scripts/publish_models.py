#!/usr/bin/env python3
"""
CapsWriter Desktop - Model Asset Publisher

Uploads ASR model archives as separate assets to a GitHub release.
Requires GitHub CLI (gh) to be installed and authenticated.

Usage:
    python scripts/publish_models.py --tag v0.1.0 --models-dir D:\\BaiduNetdiskDownload\\models

    # Upload only specific models:
    python scripts/publish_models.py --tag v0.1.0 --models-dir ./models --only Qwen3 SenseVoice

    # Dry run (no upload, just list files):
    python scripts/publish_models.py --tag v0.1.0 --models-dir ./models --dry-run
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import List, Optional

# Fix Windows console encoding to support UTF-8 emoji output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


# ── Model registry ──────────────────────────────────────────────────────────
MODEL_REGISTRY = [
    {
        "filename": "Sensevoice-Small-ONNX-int8.zip",
        "description": "SenseVoice Small (ONNX int8 量化版)",
    },
    {
        "filename": "Sensevoice-Small-ONNX-fp16.zip",
        "description": "SenseVoice Small (ONNX fp16)",
    },
    {
        "filename": "Qwen3-ASR-1.7B-q4_k.zip",
        "description": "Qwen3 ASR 1.7B (Q4_K 量化)",
    },
    {
        "filename": "Qwen3-ASR-1.7B-q5_k.zip",
        "description": "Qwen3 ASR 1.7B (Q5_K 量化)",
    },
    {
        "filename": "Qwen3-ForcedAligner-0.6B.zip",
        "description": "Qwen3 Forced Aligner 0.6B",
    },
    {
        "filename": "Paraformer.zip",
        "description": "Paraformer ASR model",
    },
    {
        "filename": "Fun-ASR-Nano-GGUF.zip",
        "description": "FunASR Nano GGUF model",
    },
    {
        "filename": "Punct-CT-Transformer.zip",
        "description": "Punctuation CT-Transformer",
    },
    {
        "filename": "SenseVoice-Small.zip",
        "description": "SenseVoice Small (原始目录打包)",
        "from_dir": "SenseVoice-Small",
    },
]


def find_gh() -> str:
    """Find the gh CLI path."""
    gh = shutil.which("gh")
    if gh:
        return gh
    for candidate in [
        r"C:\Program Files\GitHub CLI\gh.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\GitHub CLI\gh.exe"),
    ]:
        if os.path.isfile(candidate):
            return candidate
    print("❌ GitHub CLI (gh) not found.", file=sys.stderr)
    print("   Install: https://cli.github.com/", file=sys.stderr)
    sys.exit(1)


def check_gh_auth(gh: str) -> bool:
    """Check if gh is authenticated."""
    result = subprocess.run([gh, "auth", "status"], capture_output=True, text=True)
    return result.returncode == 0


def gh_cmd(gh: str, repo: Optional[str]) -> List[str]:
    """Return the base gh command with optional --repo flag."""
    cmd = [gh]
    if repo:
        cmd.extend(["--repo", repo])
    return cmd


def get_release_url(gh: str, tag: str, repo: Optional[str] = None) -> Optional[str]:
    """Get the release HTML URL for a given tag."""
    cmd = gh_cmd(gh, repo) + ["release", "view", tag, "--json", "url"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        data = json.loads(result.stdout)
        return data.get("url")
    return None


def upload_asset(gh: str, tag: str, file_path: Path, label: str = "", repo: Optional[str] = None) -> bool:
    """Upload a single file as a release asset."""
    cmd = gh_cmd(gh, repo) + ["release", "upload", tag, str(file_path), "--clobber"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ Failed: {result.stderr.strip()}")
        return False
    return True


def zip_directory(source_dir: Path, output_zip: Path) -> bool:
    """Create a zip archive from a directory."""
    try:
        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_STORED) as zf:
            for file in source_dir.rglob("*"):
                if file.is_file():
                    arcname = file.relative_to(source_dir.parent)
                    zf.write(file, arcname)
        return True
    except Exception as e:
        print(f"  ❌ Zip failed: {e}")
        return False


def collect_upload_files(
    models_dir: Path, only: Optional[List[str]] = None
) -> List[tuple]:
    """Collect files to upload based on the registry."""
    uploads = []

    for model in MODEL_REGISTRY:
        filename = model["filename"]
        description = model["description"]

        # Filter by --only
        if only and not any(o.lower() in filename.lower() for o in only):
            continue

        if "from_dir" in model:
            source_dir = models_dir / model["from_dir"]
            if source_dir.exists() and source_dir.is_dir():
                zip_path = models_dir / filename
                print(f"📦 Creating {filename} from {model['from_dir']}/...")
                if zip_directory(source_dir, zip_path):
                    uploads.append((zip_path, description))
                    print(f"   ✅ Created ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")
                else:
                    print(f"   ⚠️  Failed to create {filename}")
            else:
                print(f"⚠️  Directory {source_dir} not found, skipping {filename}")
        else:
            file_path = models_dir / filename
            if file_path.exists():
                size_mb = file_path.stat().st_size / 1024 / 1024
                uploads.append((file_path, f"{description} ({size_mb:.1f}MB)"))
            else:
                print(f"⚠️  {filename} not found in {models_dir}, skipping")

    return uploads


def main():
    parser = argparse.ArgumentParser(
        description="Upload CapsWriter Desktop ASR model assets to GitHub release"
    )
    parser.add_argument("--tag", "-t", required=True, help="Release tag (e.g. v0.1.0)")
    parser.add_argument("--models-dir", "-m", required=True, help="Path to models directory")
    parser.add_argument("--only", "-o", nargs="*", help="Only upload models matching substrings")
    parser.add_argument("--dry-run", action="store_true", help="List files without uploading")
    parser.add_argument("--repo", "-r", help="GitHub repository (owner/repo)")

    args = parser.parse_args()

    models_dir = Path(args.models_dir)
    if not models_dir.exists():
        print(f"❌ Models directory not found: {models_dir}")
        sys.exit(1)

    gh = find_gh()

    if not args.dry_run and not check_gh_auth(gh):
        print("❌ GitHub CLI not authenticated. Run: gh auth login")
        sys.exit(1)

    print(f"\n🔍 Scanning models directory: {models_dir}\n")
    uploads = collect_upload_files(models_dir, only=args.only)

    if not uploads:
        print("\n❌ No model files found to upload.")
        sys.exit(1)

    total_size = sum(f.stat().st_size for f, _ in uploads)
    print(f"\n📋 Upload plan for release {args.tag}:")
    print(f"   Total: {len(uploads)} file(s), {total_size / 1024 / 1024 / 1024:.2f} GB\n")

    for file_path, desc in uploads:
        size_mb = file_path.stat().st_size / 1024 / 1024
        print(f"   📎 {file_path.name:45s} {size_mb:8.1f} MB  {desc}")

    print()

    if args.dry_run:
        print("🏃 Dry run mode - no files uploaded.")
        return

    if sys.stdin.isatty():
        confirm = input("Upload these files? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Cancelled.")
            sys.exit(0)

    print("\n🚀 Uploading model assets...\n")
    success = 0
    failed = 0

    for file_path, desc in uploads:
        print(f"  ⏳ {file_path.name}...")
        if upload_asset(gh, args.tag, file_path, desc, repo=args.repo):
            print(f"  ✅ {file_path.name} uploaded")
            success += 1
        else:
            failed += 1

    print(f"\n{'='*60}")
    print(f"✅ {success} uploaded, ❌ {failed} failed")

    release_url = get_release_url(gh, args.tag, repo=args.repo)
    if release_url:
        print(f"\n🔗 Release: {release_url}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
