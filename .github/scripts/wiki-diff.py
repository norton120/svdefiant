#!/usr/bin/env python3
"""Build candidate URLs and a diff blob from a gollum event payload.

Reads the JSON-encoded `pages` array from env PAGES, runs `git show` against a
local clone of the wiki at ./wiki, and writes:

  argv[1]: diff blob path  (`git show --stat <sha>` for each page, concatenated)
  argv[2]: candidate URLs path (newline-separated html_url values)

Exits 0 with empty files if the payload has no usable pages.
"""
import json
import os
import subprocess
import sys


def main() -> None:
    diff_path, urls_path = sys.argv[1], sys.argv[2]
    pages = json.loads(os.environ.get("PAGES", "[]"))

    urls: list[str] = []
    diffs: list[str] = []

    for p in pages:
        if p.get("html_url"):
            urls.append(p["html_url"])
        name = p.get("page_name") or p.get("title") or ""
        sha = p.get("sha")
        header = f"=== Wiki page: {name} (action={p.get('action')}) ===\n"
        if not sha:
            diffs.append(header + "(no sha in event payload)\n")
            continue
        try:
            show = subprocess.check_output(
                ["git", "-C", "wiki", "show", "--stat", sha],
                text=True, errors="replace",
            )
        except subprocess.CalledProcessError as exc:
            show = f"(git show failed: {exc})\n"
        diffs.append(header + show + "\n")

    with open(urls_path, "w") as f:
        f.write("\n".join(urls))
    with open(diff_path, "w") as f:
        f.write("\n".join(diffs)[:200000])


if __name__ == "__main__":
    main()
