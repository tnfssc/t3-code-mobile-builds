#!/usr/bin/env python3
"""Publish only after APK identity, alignment, and persistent signature pass."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
plan = json.loads((root / "build-plan.json").read_text())
dist = root / "dist"
apk = dist / "t3-code-mobile-builds-arm64.apk"
plan.update(apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
            signing_certificate_sha256=os.environ["APK_CERTIFICATE_SHA256"],
            build_url=f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
(dist / "build-info.json").write_text(json.dumps(plan, indent=2) + "\n")
shutil.copyfile(root / "upstream/LICENSE", dist / "UPSTREAM-LICENSE.txt")
files = [apk, dist / "build-info.json", dist / "UPSTREAM-LICENSE.txt"]
(dist / "SHA256SUMS").write_text("".join(
    f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in files
))
notes = f"""Independent Android build of [T3 Code]({plan['upstream_release']}).

- Upstream: `{plan['upstream_tag']}` / `{plan['upstream_sha']}`
- Android app: `{plan['version_name']}`, orchestration protocol {plan['orchestration_protocol']}
- CPU: ARM64 (modern Android phones); Android 7.0 or newer
- Package: `{plan['package']}`; installs alongside the official app
- Supports direct connections (LAN/Tailscale). T3 Connect account login and upstream OTA updates are disabled.
- Signed with the same independent certificate as previous builds; install new APKs over the previous Mobile Builds app.
- [Build log]({plan['build_url']})

Download **t3-code-mobile-builds-arm64.apk**, allow installation from your browser when prompted, then pair your server in this app.
Your official app's saved connections stay in the official app; pair this separate app once.

This is an unofficial community build, not a release from T3 Tools. Upstream source and MIT license are preserved; dependencies retain their bundled notices.
"""
notes_path = dist / "release-notes.md"
notes_path.write_text(notes)
subprocess.run(["gh", "release", "create", plan["release_tag"],
    "--repo", os.environ["GITHUB_REPOSITORY"], "--target", os.environ["GITHUB_SHA"],
    "--title", f"T3 Code Mobile {plan['version_name']}", "--notes-file", str(notes_path),
    "--latest", *map(str, files), str(dist / "SHA256SUMS")], check=True)
