#!/usr/bin/env python3
"""Decide whether a content/wiki change belongs on the public What's New page.

Reads context from env:
  SOURCE         "content" or "wiki"
  CHANGE_DATE    ISO date (YYYY-MM-DD) for the resulting entry
  CANDIDATE_URLS newline-separated list of plausible reader landing URLs
  DIFF_TEXT      unified diff or page-by-page summary; passed verbatim to the model

On a significant change, writes a YAML fragment to ENTRY_FILE (one entry, suitable
for appending to data/whatsnew.yaml's `entries:` list) and prints `significant=true`
to GITHUB_OUTPUT. On any other outcome (insignificant, parse failure, API error)
prints `significant=false` and writes nothing.
"""
import json
import os
import sys

import anthropic

SYSTEM_PROMPT = """You decide whether a recent change to the S/V Defiant website (a Hugo blog/gallery) or its companion GitHub wiki belongs on the public "What's New" page. Friends and family read that page to catch up on new posts and significant additions without having to search the whole site.

Call the `record_update` tool exactly once.

Set `significant=true` ONLY for substantial new contributions, such as:
- A brand new blog post or gallery album
- A brand new wiki page
- A major addition to an existing page — a new section with at least roughly 150 added lines, or several substantial paragraphs of new prose

Set `significant=false` for everything else, including:
- Typo fixes, formatting tweaks, link corrections
- Spec or measurement updates, image swaps, captions
- Small clarifications or single-paragraph edits
- Drafts (`draft: true` in front matter)
- Many small edits across multiple files that still don't add up to a substantive new contribution

When significant, write `title` and `summary` in a friendly, casual voice, as if telling a friend "I just put up something new." `summary` is one short sentence, ideally under 20 words. Prefer the page's own title for `title` when one exists.

Pick `url` as the single most logical entry point for a reader — the one page they should land on to see this change. Choose only from the candidate URLs you are given."""

TOOL = {
    "name": "record_update",
    "description": "Record whether the change is significant enough for the What's New page, and if so, the entry to publish.",
    "input_schema": {
        "type": "object",
        "properties": {
            "significant": {"type": "boolean"},
            "title": {"type": "string"},
            "url": {"type": "string"},
            "summary": {"type": "string"},
            "reasoning": {
                "type": "string",
                "description": "One short sentence on why this is or isn't significant. Logged, not published.",
            },
        },
        "required": ["significant", "reasoning"],
    },
}


def classify(source: str, candidate_urls: list[str], diff_text: str) -> dict:
    client = anthropic.Anthropic()
    user_msg = (
        f"Source: {source}\n"
        f"Candidate URLs (pick one):\n"
        + "\n".join(f"  - {u}" for u in candidate_urls)
        + "\n\nChanges:\n"
        + diff_text
    )
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_update"},
        messages=[{"role": "user", "content": user_msg}],
    )
    for block in msg.content:
        if block.type == "tool_use" and block.name == "record_update":
            return block.input
    return {"significant": False, "reasoning": "no tool call returned"}


def yaml_escape(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def derive_source_label(source: str, url: str) -> str:
    if source == "wiki":
        return "wiki"
    if url.startswith("/blog/"):
        return "blog"
    if url.startswith("/gallery/"):
        return "gallery"
    return source


def write_entry(date: str, source: str, decision: dict, entry_file: str) -> None:
    title = decision["title"]
    url = decision["url"]
    summary = decision.get("summary", "")
    label = derive_source_label(source, url)
    lines = [
        f"  - date: {yaml_escape(date)}",
        f"    title: {yaml_escape(title)}",
        f"    url: {yaml_escape(url)}",
        f"    summary: {yaml_escape(summary)}",
        f"    source: {yaml_escape(label)}",
    ]
    with open(entry_file, "w") as f:
        f.write("\n".join(lines) + "\n")


def emit_output(significant: bool, reasoning: str) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return
    with open(github_output, "a") as f:
        f.write(f"significant={'true' if significant else 'false'}\n")
        f.write(f"reasoning<<EOF\n{reasoning}\nEOF\n")


def main() -> None:
    source = os.environ["SOURCE"]
    change_date = os.environ["CHANGE_DATE"]
    candidate_urls_raw = os.environ.get("CANDIDATE_URLS", "").strip()
    diff_text = os.environ.get("DIFF_TEXT", "")
    entry_file = os.environ["ENTRY_FILE"]

    candidate_urls = [u.strip() for u in candidate_urls_raw.splitlines() if u.strip()]
    if not candidate_urls:
        print("no candidate URLs; treating as not significant", file=sys.stderr)
        emit_output(False, "no candidate URLs")
        return

    if not diff_text.strip():
        print("empty diff; treating as not significant", file=sys.stderr)
        emit_output(False, "empty diff")
        return

    try:
        decision = classify(source, candidate_urls, diff_text)
    except Exception as exc:
        print(f"classification failed: {exc}", file=sys.stderr)
        emit_output(False, f"api error: {exc}")
        return

    print("decision:", json.dumps(decision, indent=2))
    if not decision.get("significant"):
        emit_output(False, decision.get("reasoning", ""))
        return

    if decision.get("url") not in candidate_urls:
        print(f"model returned URL not in candidates: {decision.get('url')}", file=sys.stderr)
        emit_output(False, "model returned out-of-band url")
        return

    if not decision.get("title") or not decision.get("summary"):
        print("model marked significant but missing fields", file=sys.stderr)
        emit_output(False, "missing title or summary")
        return

    write_entry(change_date, source, decision, entry_file)
    emit_output(True, decision.get("reasoning", ""))


if __name__ == "__main__":
    main()
