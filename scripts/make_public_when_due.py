#!/usr/bin/env python3
"""Flip repo visibility to public on/after 2026-10-24 (America/Los_Angeles).

Safe to run daily via Actions: no-ops until the scheduled date.
Requires `gh` auth with `repo` scope.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

PUBLIC_ON = date(2026, 10, 24)
PACIFIC = ZoneInfo("America/Los_Angeles")


def main() -> int:
    today = datetime.now(PACIFIC).date()
    repo = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("SEC_FIN_EMBEDDINGS_REPO")
    if not repo:
        # Infer from git remote
        try:
            url = subprocess.check_output(
                ["git", "remote", "get-url", "origin"], text=True
            ).strip()
            if "github.com" in url:
                repo = url.rstrip("/").split("github.com")[-1].lstrip("/:").removesuffix(".git")
        except Exception:
            repo = ""
    if not repo:
        print("No repo identity; set GITHUB_REPOSITORY", file=sys.stderr)
        return 2

    print(f"today_pacific={today} public_on={PUBLIC_ON} repo={repo}")
    if today < PUBLIC_ON:
        print("noop: before public date")
        return 0

    # Already public?
    vis = subprocess.check_output(
        ["gh", "repo", "view", repo, "--json", "visibility", "-q", ".visibility"],
        text=True,
    ).strip()
    if vis.upper() == "PUBLIC":
        print("already public")
        return 0

    subprocess.check_call(["gh", "repo", "edit", repo, "--visibility", "public", "--accept-visibility-change-consequences"])
    print("flipped to public")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
