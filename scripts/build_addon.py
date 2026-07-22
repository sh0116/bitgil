#!/usr/bin/env python3
"""Assemble the installable Bitgil NVDA add-on (`.nvda-addon`).

Layout produced (a zip renamed to .nvda-addon):

    manifest.ini
    globalPlugins/bitgil/…                (the GPLv2 add-on)
    globalPlugins/bitgil/lib/bitgil_core (vendored MIT core, on sys.path)
    globalPlugins/bitgil/profile_packs/*.yaml   (CC BY 4.0 packs)

Run: python scripts/build_addon.py  ->  dist/bitgil-<version>.nvda-addon
"""

from __future__ import annotations

import os
import shutil
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(REPO, "build", "addon")
DIST = os.path.join(REPO, "dist")
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")

# Pure-Python runtime deps to vendor under lib/ so they resolve inside NVDA's
# own Python (which has none of our deps). PyYAML is required for profile packs.
# NOTE: native-extension deps (Pillow, imagehash) and provider SDKs are NOT
# vendored here — they need platform-specific (win_amd64/win32) wheels matching
# NVDA's Python. Fetch those with, e.g.:
#   pip download --only-binary=:all: --platform win_amd64 --python-version 3.11 \
#       Pillow imagehash anthropic  -d build/wheels
# then unpack into lib/. Until then, live-mode change detection and cloud
# providers require those to be present in NVDA's environment.
_VENDOR_PURE = ["yaml"]  # import names (PyYAML installs as `yaml`)


def _package_dir(import_name: str) -> str | None:
	"""Locate an installed pure-Python package's directory to copy into lib/."""
	import importlib.util

	spec = importlib.util.find_spec(import_name)
	if spec and spec.origin and os.path.basename(spec.origin) == "__init__.py":
		return os.path.dirname(spec.origin)
	return None


def _version() -> str:
	with open(os.path.join(REPO, "addon", "manifest.ini"), encoding="utf-8") as f:
		for line in f:
			if line.strip().startswith("version"):
				return line.split("=", 1)[1].strip()
	return "0.0.0"


def build() -> str:
	if os.path.exists(BUILD):
		shutil.rmtree(BUILD)
	os.makedirs(BUILD)
	os.makedirs(DIST, exist_ok=True)

	# 1. add-on body + manifest
	shutil.copy(os.path.join(REPO, "addon", "manifest.ini"), os.path.join(BUILD, "manifest.ini"))
	shutil.copytree(
		os.path.join(REPO, "addon", "globalPlugins"),
		os.path.join(BUILD, "globalPlugins"),
		ignore=_IGNORE,
	)

	bitgil_dir = os.path.join(BUILD, "globalPlugins", "bitgil")

	# 2. vendor the MIT core under lib/ (resolved via sys.path at runtime)
	shutil.copytree(
		os.path.join(REPO, "core", "bitgil_core"),
		os.path.join(bitgil_dir, "lib", "bitgil_core"),
		ignore=_IGNORE,
	)

	# 2b. vendor pure-Python runtime deps (e.g. PyYAML) alongside the core
	lib = os.path.join(bitgil_dir, "lib")
	for mod in _VENDOR_PURE:
		src = _package_dir(mod)
		if src:
			shutil.copytree(src, os.path.join(lib, os.path.basename(src)), ignore=_IGNORE)
		else:
			print(f"warning: could not locate pure-Python dep '{mod}' to vendor")

	# 3. bundle the CC BY 4.0 profile packs
	packs = os.path.join(bitgil_dir, "profile_packs")
	os.makedirs(packs)
	for name in os.listdir(os.path.join(REPO, "profiles")):
		if name.endswith(".yaml"):
			shutil.copy(os.path.join(REPO, "profiles", name), os.path.join(packs, name))

	# 4. zip -> .nvda-addon
	out = os.path.join(DIST, f"bitgil-{_version()}.nvda-addon")
	if os.path.exists(out):
		os.remove(out)
	with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
		for root, _dirs, files in os.walk(BUILD):
			for fn in files:
				abs_path = os.path.join(root, fn)
				z.write(abs_path, os.path.relpath(abs_path, BUILD))
	return out


if __name__ == "__main__":
	path = build()
	print(f"built: {path}")
