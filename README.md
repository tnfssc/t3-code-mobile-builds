# T3 Code Mobile Builds

Independent, signed Android APKs built from [T3 Code](https://github.com/pingdotgg/t3code)'s published nightly source. This repository holds the build automation, not a fork of the app.

Download **[t3-code-mobile-builds-arm64.apk](https://github.com/tnfssc/t3-code-mobile-builds/releases/latest/download/t3-code-mobile-builds-arm64.apk)** from the latest successful release. Supports ARM64 Android phones running Android 7.0 or newer. Install it, then pair your T3 server in the app. The app supports orchestration V2.

The app is named **T3 Code Mobile Builds**, uses `com.tnfssc.t3code.mobilebuilds`, and installs alongside the official Play Store app. It has separate saved connections and settings. Subsequent APKs use the same signing certificate and can be installed as updates without uninstalling.

## Daily builds

GitHub Actions checks the latest published upstream nightly daily at **02:23 UTC / 06:23 Asia/Dubai**. GitHub may delay scheduled runs. It builds only when mobile code, shared dependencies, build assets, lockfiles, or this repository's build recipe differ from the latest successful release. A web/server-only source change does not by itself trigger a build. Failed builds do not advance the comparison baseline. The check uses GitHub's source tree API; unchanged checks do not download the source, install dependencies or set up Android.

Use **Actions → Android APK → Run workflow** for a manual release. Leave `upstream_tag` empty to use the newest nightly, or enter an exact published nightly tag. `force` defaults to enabled so a manual run publishes even when inputs are unchanged; disable it for a check-only run. Pushes only run quick automation tests. Releases include the upstream commit, input fingerprint, APK checksum, signing-certificate fingerprint, upstream MIT license and build-log link.

From the GitHub CLI:

```sh
gh workflow run android.yml --repo tnfssc/t3-code-mobile-builds
# Or choose a specific published nightly:
gh workflow run android.yml --repo tnfssc/t3-code-mobile-builds \
  -f upstream_tag=v0.0.46-nightly.20261003.2623 -f force=true
```

## CI time and cost

This public repository uses standard `ubuntu-24.04` runners, not paid larger runners. [GitHub documents free Actions usage for public repositories on standard hosted runners](https://docs.github.com/en/billing/concepts/product-billing/github-actions). The workflow builds ARM64 only, caches package-manager and Gradle dependencies, enables Gradle's build cache, serializes release builds, and caps a build at 60 minutes. Failed-build diagnostics expire after three days; APKs are stored as release assets rather than duplicate Actions artifacts. Cold native builds take longer than unchanged daily checks.

## Distribution differences

- Direct LAN and Tailscale pairing is supported.
- T3 Connect account login and official Expo over-the-air updates are disabled. Install updates from this repository's releases.
- Store push credentials are not included. Local notification behavior remains in the source; official cloud push delivery is not configured.
- The app is a release build with JavaScript bundled, so no Metro server, Expo login or development client is needed.
- These are unofficial community builds. The source is licensed by T3 Tools under MIT; dependency notices remain bundled in the app.

## Signing and maintenance

The workflow requires GitHub Actions secrets `APK_KEYSTORE_BASE64`, `APK_KEYSTORE_PASSWORD`, and `APK_KEY_PASSWORD`. Alias: `t3-mobile-builds`. The repository variable `APK_CERTIFICATE_SHA256` pins the expected public certificate fingerprint. The release is published only after signature, alignment, package and bundled-JavaScript checks pass.

Keep the original signing key backed up. Losing it prevents future APKs from updating installed copies. Never commit the keystore or passwords. A custom signature cannot update or replace the official Play Store package, which is why this app has its own identity.

To inspect a build, start with `build-info.json` in its release. The upstream snapshot is pinned by full commit SHA. The small Expo configuration wrapper is in `scripts/prepare-build.py`; upstream source is fetched fresh by the workflow.

Run automation tests locally:

```sh
python3 -m unittest discover -s tests -v
```
