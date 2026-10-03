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


def recipe_fingerprint(builder=ROOT):
    digest = hashlib.sha256()
    for pattern in ["build-config.json", "scripts/*", ".github/workflows/*.yml"]:
        for path in sorted(builder.glob(pattern)):
            if path.is_file():
                digest.update(str(path.relative_to(builder)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def source_fingerprint(source):
    if b"apps/mobile/app.config.ts" not in source:
        raise ValueError("Upstream checkout does not contain the mobile app")
    return hashlib.sha256(source).hexdigest()


def selected_tree(tree):
    if tree.get("truncated"):
        raise RuntimeError("Upstream tree was truncated; cannot safely check changes")
    entries = [entry for entry in tree["tree"] if entry["type"] != "tree" and any(
        entry["path"] == path or entry["path"].startswith(path + "/") for path in INPUT_PATHS
    )]
    return "".join(f"{e['mode']} {e['type']} {e['sha']}\t{e['path']}\n"
                   for e in sorted(entries, key=lambda entry: entry["path"])).encode()


def input_fingerprint(upstream, builder=ROOT):
    source = subprocess.check_output(
        ["git", "ls-tree", "-r", "HEAD", "--", *INPUT_PATHS], cwd=upstream
    )
    return hashlib.sha256((source_fingerprint(source) + recipe_fingerprint(builder)).encode()).hexdigest()


def latest_build():
    latest = api(f"repos/{os.environ['GITHUB_REPOSITORY']}/releases/latest", missing_ok=True)
    if not latest:
        return {}
    asset = next((a for a in latest["assets"] if a["name"] == "build-info.json"), None)
    if asset is None:
        raise RuntimeError("Latest release has no build-info.json; refusing an ambiguous comparison")
    with urlopen(asset["browser_download_url"], timeout=30) as response:
        return json.load(response)


def gate():
    config = json.loads((ROOT / "build-config.json").read_text())
    stable = api(f"repos/{config['upstream']}/releases/latest")
    if stable["draft"] or stable["prerelease"] or not re.fullmatch(r"v\d+\.\d+\.\d+", stable["tag_name"]):
        raise RuntimeError("Latest upstream release is not a published stable desktop release")
    previous = latest_build()
    force = os.environ.get("FORCE_BUILD", "false") == "true"
    eligible = force or stable["tag_name"] != previous.get("stable_trigger_tag")
    plan = {"stable_trigger_tag": stable["tag_name"], "stable_trigger_release": stable["html_url"],
            "stable_trigger_published_at": stable["published_at"]}
    (ROOT / "build-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    output(eligible=str(eligible).lower(), stable_tag=stable["tag_name"])
    message = ("Manual release requested." if force else "New stable desktop release; build its latest mobile nightly.") if eligible else "Stable desktop release unchanged; skipping the APK build."
    print(message)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as destination:
        destination.write(f"## Stable release check\n\n{message}\n\nStable: {stable['tag_name']}\n")


def select():
    config = json.loads((ROOT / "build-config.json").read_text())
    repo = config["upstream"]
    nightly_pattern = r"v\d+\.\d+\.\d+-nightly\.\d{8}\.\d+"
    requested = os.environ.get("UPSTREAM_TAG", "").strip()
    release = None
    if requested:
        if not re.fullmatch(nightly_pattern, requested):
            raise ValueError("Manual source must be an exact published vX.Y.Z-nightly.YYYYMMDD.N tag")
        release = api(f"repos/{repo}/releases/tags/{requested}")
        if release["draft"]:
            raise ValueError("Cannot build an unpublished draft release")
    else:
        for page in range(1, 6):
            releases = api(f"repos/{repo}/releases?per_page=30&page={page}")
            eligible = [r for r in releases if not r["draft"] and re.fullmatch(nightly_pattern, r["tag_name"])]
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
    plan_path = ROOT / "build-plan.json"
    plan = json.loads(plan_path.read_text())
    plan.update(upstream=repo, upstream_tag=release["tag_name"],
                upstream_sha=commit, upstream_release=release["html_url"])
    (ROOT / "build-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    output(sha=commit, tag=release["tag_name"])
    print(f"Selected {repo}@{release['tag_name']} ({commit})")


def check():
    plan_path = ROOT / "build-plan.json"
    plan = json.loads(plan_path.read_text())
    previous = latest_build()
    recipe = recipe_fingerprint()
    # No source checkout or SDK/dependency setup for an unchanged daily check.
    if previous.get("upstream_sha") == plan["upstream_sha"] and previous.get("source_fingerprint"):
        source = previous["source_fingerprint"]
    else:
        tree = api(f"repos/{plan['upstream']}/git/trees/{plan['upstream_sha']}?recursive=1")
        source = source_fingerprint(selected_tree(tree))
    fingerprint = hashlib.sha256((source + recipe).encode()).hexdigest()
    force = os.environ.get("FORCE_BUILD", "false") == "true"
    new_stable = plan.get("stable_trigger_tag") != previous.get("stable_trigger_tag")
    needed = fingerprint != previous.get("input_fingerprint") or force or new_stable
    run = int(os.environ["GITHUB_RUN_NUMBER"])
    release_tag = f"mobile-{plan['upstream_tag'].removeprefix('v')}-{fingerprint[:12]}-r{run}"
    plan.update(input_fingerprint=fingerprint, source_fingerprint=source, recipe_fingerprint=recipe,
                release_tag=release_tag, version_code=run)
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    output(needed=str(needed).lower(), fingerprint=fingerprint, release_tag=release_tag)
    message = "Building the selected mobile nightly for this release." if needed else "Mobile build inputs unchanged; skipping."
    print(message)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as destination:
        destination.write(f"## Upstream check\n\n{message}\n\nUpstream: {plan['upstream_tag']}\n")


if __name__ == "__main__":
    {"gate": gate, "select": select, "check": check}[sys.argv[1]]()
