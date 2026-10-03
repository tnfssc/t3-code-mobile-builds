#!/usr/bin/env python3
"""Change only distribution identity and disable upstream OTA/cloud credentials."""
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
config = json.loads((root / "build-config.json").read_text())
plan_path = root / "build-plan.json"
plan = json.loads(plan_path.read_text())
source = root / "upstream"
path = source / "apps/mobile/app.config.ts"
text = path.read_text()
match = re.search(r'^  version: "([0-9]+\.[0-9]+\.[0-9]+)"', text, re.M)
if match is None or text.count("export default config;") != 1:
    raise RuntimeError("Upstream Expo config changed; review the build wrapper")
app_version = match[1]
nightly = plan["upstream_tag"].split("-", 1)[1]
version_name = f"{app_version}+{nightly}.build{plan['version_code']}"
overrides = f"""
// Independent, signed GitHub distribution. Keep upstream store installs separate.
config.name = {json.dumps(config['name'])};
config.slug = "t3-code-mobile-builds";
config.scheme = {json.dumps(config['scheme'])};
config.version = {json.dumps(version_name)};
config.android = {{ ...config.android, package: {json.dumps(config['package'])}, versionCode: {plan['version_code']} }};
config.updates = {{ enabled: false }};
config.runtimeVersion = {{ policy: "appVersion" }};
delete config.owner;
if (config.extra) delete config.extra.eas;
export default config;
"""
path.write_text(text.replace("export default config;", overrides))
plan.update(app_version=app_version, version_name=version_name,
            package=config["package"], architectures=config["architectures"],
            orchestration_protocol=2, ota_updates=False, cloud_features=False)
# Fail closed if upstream drops/moves protocol negotiation.
contracts = (source / "packages/contracts/src/environment.ts").read_text()
if not re.search(r"ORCHESTRATION_PROTOCOL_VERSION\s*=\s*2\b", contracts):
    raise RuntimeError("Expected orchestration protocol 2; review mobile/server compatibility")
plan_path.write_text(json.dumps(plan, indent=2) + "\n")
print(f"Prepared {config['package']} {version_name}")
