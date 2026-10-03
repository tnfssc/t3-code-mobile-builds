#!/usr/bin/env python3
"""Select a published upstream nightly; compare actual mobile build inputs."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
INPUT_PATHS = [
    "apps/mobile", "packages/client-runtime", "packages/contracts", "packages/shared",
    "scripts", "patches", "assets", "native/libghostty-vt", "package.json",
    "pnpm-lock.yaml", "pnpm-workspace.yaml", "tsconfig.json", "tsconfig.base.json",
    "third-party-licenses.config.json", "third-party-notices", "LICENSE",
]


def api(path, *, missing_ok=False):
    request = Request("https://api.github.com/" + path, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + os.environ["GH_TOKEN"],
        "User-Agent": "t3-code-mobile-builds",
    })
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        raise


def output(**values):
    with open(os.environ["GITHUB_OUTPUT"], "a") as destination:
        for key, value in values.items():
            destination.write(f"{key}={value}\n")


def input_fingerprint(upstream, builder=ROOT):
    # Hash blob IDs + paths, excluding commit SHA: web/server-only nightlies skip.
    source = subprocess.check_output(
        ["git", "ls-tree", "-r", "HEAD", "--", *INPUT_PATHS], cwd=upstream
    )
    if b"apps/mobile/app.config.ts" not in source:
        raise ValueError("Upstream checkout does not contain the mobile app")
    digest = hashlib.sha256(source)
    for pattern in ["build-config.json", "scripts/*", ".github/workflows/*.yml"]:
        for path in sorted(builder.glob(pattern)):
            if path.is_file():
                digest.update(str(path.relative_to(builder)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def select():
    config = json.loads((ROOT / "build-config.json").read_text())
    repo = config["upstream"]
    release = None
    for page in range(1, 6):
        releases = api(f"repos/{repo}/releases?per_page=100&page={page}")
        eligible = [r for r in releases if not r["draft"] and re.fullmatch(
            r"v\d+\.\d+\.\d+-nightly\.\d{8}\.\d+", r["tag_name"]
        )]
        if eligible:
            release = max(eligible, key=lambda r: r["published_at"])
            break
        if not releases:
            break
    if release is None:
        raise RuntimeError("No published upstream nightly found")
    commit = api(f"repos/{repo}/commits/{release['tag_name']}")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid upstream commit")
    plan = {"upstream": repo, "upstream_tag": release["tag_name"],
            "upstream_sha": commit, "upstream_release": release["html_url"]}
    (ROOT / "build-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    output(sha=commit, tag=release["tag_name"])
    print(f"Selected {repo}@{release['tag_name']} ({commit})")


def check():
    plan_path = ROOT / "build-plan.json"
    plan = json.loads(plan_path.read_text())
    fingerprint = input_fingerprint(ROOT / "upstream")
    latest = api(f"repos/{os.environ['GITHUB_REPOSITORY']}/releases/latest", missing_ok=True)
    previous = None
    if latest:
        asset = next((a for a in latest["assets"] if a["name"] == "build-info.json"), None)
        if asset is None:
            raise RuntimeError("Latest release has no build-info.json; refusing an ambiguous comparison")
        with urlopen(asset["browser_download_url"], timeout=30) as response:
            previous = json.load(response).get("input_fingerprint")
    force = os.environ.get("FORCE_BUILD", "false") == "true"
    needed = fingerprint != previous or force
    run = int(os.environ["GITHUB_RUN_NUMBER"])
    release_tag = f"mobile-{plan['upstream_tag'].removeprefix('v')}-{fingerprint[:12]}-r{run}"
    plan.update(input_fingerprint=fingerprint, release_tag=release_tag, version_code=run)
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    output(needed=str(needed).lower(), fingerprint=fingerprint, release_tag=release_tag)
    message = "Mobile build inputs changed; building an APK." if needed else "Mobile build inputs unchanged; skipping."
    print(message)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as destination:
        destination.write(f"## Upstream check\n\n{message}\n\nUpstream: {plan['upstream_tag']}\n")


if __name__ == "__main__":
    {"select": select, "check": check}[sys.argv[1]]()
