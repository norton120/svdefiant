#!/usr/bin/env python3
"""Match recent inbound mail (orders, shipping, deliveries) against open issues
and update the `blocked:parts` label.

Reads inbox + open issues via the `defiant` CLI, calls Anthropic with a forced
tool-use schema to get label change decisions, applies via `defiant task`.
Prints a markdown summary suitable for $GITHUB_STEP_SUMMARY.

Note: the GH Actions runner is ephemeral so `~/.defiant/inbox-state.json`
doesn't persist across runs; we pass `--all` to inbox list and skip acking.
If we ever cache `~/.defiant/` across runs (actions/cache), switch to the
default unprocessed filter and ack every email after processing for Anthropic
token savings.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import anthropic

REPO = "norton120/svdefiant"
DEFIANT = str(Path(__file__).resolve().parents[2] / "bin" / "defiant")
SINCE = os.environ.get("TRIAGE_SINCE", "14d")
MODEL = "claude-sonnet-4-6"

DELIVERY_PATTERN = re.compile(
    r"amazon|ups|fedex|usps|defender|west.?marine|jamestown|hamilton|sailrite|"
    r"harken|raymarine|chesapeake.?cove|shipped|delivered|tracking|"
    r"order.?confirmation|out.?for.?delivery",
    re.I,
)

SYSTEM_PROMPT = """You triage parts dependencies for a sailboat refit (S/V Defiant).

Inputs:
- Recent inbound mail (already filtered to delivery-related senders/subjects)
- Open GitHub issues with title, body, current labels

Decide which issues should get `blocked:parts` added or removed by calling the `apply_label_changes` tool.

Rules:
- ADD `blocked:parts` to an issue iff: the issue does NOT have it, AND the body mentions an outstanding order, AND a recent order/shipping email matches, AND no delivery confirmation has arrived.
- REMOVE `blocked:parts` from an issue iff: the issue currently has it, AND a delivery confirmation email exists for the part(s).
- Strong match requires: vendor or part name from email appears in issue body, OR tracking/order ID in both.
- "Out for delivery" is NOT delivered — keep blocked.
- If an issue tracks multiple parts, only remove when ALL have delivery confirmations.
- Ambiguous → leave alone. List relevant emails with no matching issue in `stragglers`.

Be conservative. A human reviews the output."""

TOOL = {
    "name": "apply_label_changes",
    "description": "Apply blocked:parts label changes based on inbox/issue match.",
    "input_schema": {
        "type": "object",
        "properties": {
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "issue_number": {"type": "integer"},
                        "action": {"type": "string", "enum": ["add", "remove"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["issue_number", "action", "reason"],
                },
            },
            "stragglers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Relevant emails with no matching issue (1 line each)",
            },
            "summary": {"type": "string"},
        },
        "required": ["changes", "stragglers", "summary"],
    },
}


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def fetch_inbox() -> list[dict]:
    msgs = json.loads(run([DEFIANT, "inbox", "list", "--since", SINCE, "--all"]))
    return [
        m for m in msgs
        if DELIVERY_PATTERN.search(f"{m.get('from','')} {m.get('subject','')} {m.get('snippet','')}")
    ]


def fetch_issues() -> list[dict]:
    return json.loads(run([
        DEFIANT, "task", "list", "--limit", "300", "--with-body",
    ]))


def decide(emails: list[dict], issues: list[dict]) -> dict:
    issues_compact = [
        {
            "number": i["number"],
            "title": i["title"],
            "body": (i.get("body") or "")[:1500],
            "labels": i.get("labels") or [],
        }
        for i in issues
    ]
    emails_compact = [
        {
            "from": e["from"],
            "subject": e["subject"],
            "date": e["date"],
            "snippet": e.get("snippet", ""),
        }
        for e in emails
    ]

    user_content = (
        f"## Emails ({len(emails_compact)})\n```json\n"
        f"{json.dumps(emails_compact, indent=2)}\n```\n\n"
        f"## Open issues ({len(issues_compact)})\n```json\n"
        f"{json.dumps(issues_compact, indent=2)}\n```"
    )

    msg = anthropic.Anthropic().messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "apply_label_changes"},
        messages=[{"role": "user", "content": user_content}],
    )
    for block in msg.content:
        if block.type == "tool_use" and block.name == "apply_label_changes":
            return block.input
    return {"changes": [], "stragglers": [], "summary": "no decisions returned"}


def apply_changes(changes: list[dict]) -> list[dict]:
    out = []
    for c in changes:
        flag = "--blocked-parts" if c["action"] == "add" else "--no-blocked-parts"
        try:
            subprocess.run(
                [DEFIANT, "task", "update", str(c["issue_number"]), flag],
                check=True, capture_output=True, text=True,
            )
            out.append({**c, "ok": True})
        except subprocess.CalledProcessError as e:
            out.append({**c, "ok": False, "error": (e.stderr or "").strip()})
    return out


def report(applied: list[dict], stragglers: list[str], summary: str) -> None:
    print("# Triage report\n")
    print(summary, "\n")
    if applied:
        print("| Issue | Action | Reason | OK |")
        print("|---|---|---|---|")
        for c in applied:
            ok = "✓" if c.get("ok") else f"✗ {c.get('error','')}"
            print(f"| #{c['issue_number']} | {c['action']} | {c['reason']} | {ok} |")
    else:
        print("_no label changes_\n")
    if stragglers:
        print("\n## Stragglers (no matching issue)")
        for s in stragglers:
            print(f"- {s}")


def main() -> None:
    emails = fetch_inbox()
    issues = fetch_issues()
    print(f"emails: {len(emails)}, issues: {len(issues)}", file=sys.stderr)

    if not emails:
        print("# Triage report\n\n_No delivery-relevant emails in the last "
              f"{SINCE}._")
        return

    decision = decide(emails, issues)
    applied = apply_changes(decision.get("changes", []))
    report(applied, decision.get("stragglers", []), decision.get("summary", ""))


if __name__ == "__main__":
    main()
