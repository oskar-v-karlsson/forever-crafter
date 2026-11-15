#!/usr/bin/env python3
"""The version of the next release, for .github/workflows/release.yml.

Releases are tagged vX.Y.Z. Each push to main bumps the patch of the higher of the newest vX.Y.Z tag and the .toc
## Version. A .toc version above the newest tag (a manual minor/major bump in a PR) is used as is. Old tags like
v0.1.0-5f1a87c are ignored. Prints nothing when HEAD already has a vX.Y.Z tag (a re-run): no new release.

    python tools/release_version.py          # reads the .toc and the git tags of the checkout
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOC = os.path.join(ROOT, "ForeverCrafter", "ForeverCrafter.toc")
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse(text):
    """'v1.2.3' / '1.2.3' → (1, 2, 3), None for anything else (e.g. v0.1.0-5f1a87c)."""
    m = SEMVER.match(text.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def next_version(toc_version, tags, head_tags=()):
    """→ 'X.Y.Z' for the next release, or None when HEAD is already released."""
    if any(parse(t) for t in head_tags):
        return None
    toc = parse(toc_version)
    if not toc:
        raise ValueError(f".toc Version {toc_version!r} is not X.Y.Z")
    released = [v for v in map(parse, tags) if v]
    latest = max(released) if released else None
    if latest and toc > latest:
        return "%d.%d.%d" % toc
    base = max(toc, latest) if latest else toc
    return "%d.%d.%d" % (base[0], base[1], base[2] + 1)


def toc_version():
    with open(TOC, encoding="utf-8") as f:
        m = re.search(r"^## Version: *(\S+)", f.read(), re.M)
    return m.group(1)


def git_tags(*args):
    out = subprocess.run(["git", "tag", "--list", "v*", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return out.stdout.split()


def main():
    v = next_version(toc_version(), git_tags(), git_tags("--points-at", "HEAD"))
    if v:
        print(v)


if __name__ == "__main__":
    sys.exit(main())
