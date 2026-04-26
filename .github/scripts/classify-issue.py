#!/usr/bin/env python3
"""Classify a refit task issue into the project's label vocabulary.

Reads ISSUE_TITLE and ISSUE_BODY from env, calls Anthropic with a forced
tool-use schema, writes a comma-separated `labels=` line to GITHUB_OUTPUT.
On any failure, writes an empty labels list — the workflow still adds the
issue to the project, the user labels it manually.
"""
import os
import sys

import anthropic

SYSTEM_PROMPT = """You classify refit/maintenance tasks for a sailboat (S/V Defiant) into a fixed label vocabulary, by calling the `apply_labels` tool.

Each task gets exactly one priority, one system, at least one location, one energy level, one weather requirement, and one time estimate. Set blocked_parts only when the body clearly says parts are missing or on order — otherwise false. Make your best guess; the human will correct anything wrong.

Dimensions:
- priority: how urgent
  - p0: safety/seaworthiness blocker (can't sail safely without it)
  - p1: high (needed soon, comfort/reliability)
  - p2: normal (the usual)
  - p3: nice to have (cosmetic, optional)
- system: which boat system the task touches
  - electrical, rigging, sails, plumbing, engine, nav, hull, interior, ground-tackle, safety
- location: where on/off the boat — pick all that apply
  - indoors (in the cabin), on-deck, aloft (up the mast), underwater, dockside-only (must be tied up), underway-ok (can be done while sailing)
- energy: physical effort required
  - couch (sitting/light work), light, moderate, heavy
- weather: conditions needed
  - any, dry (no rain), calm (no wind), warm (warm temps)
- time: estimated duration
  - lt-1hr, half-day, full-day, multi-day"""

TOOL = {
    "name": "apply_labels",
    "description": "Classify the task and apply the right labels.",
    "input_schema": {
        "type": "object",
        "properties": {
            "priority": {"type": "string", "enum": ["p0", "p1", "p2", "p3"]},
            "system": {
                "type": "string",
                "enum": [
                    "electrical", "rigging", "sails", "plumbing", "engine",
                    "nav", "hull", "interior", "ground-tackle", "safety",
                ],
            },
            "location": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "indoors", "on-deck", "aloft", "underwater",
                        "dockside-only", "underway-ok",
                    ],
                },
                "minItems": 1,
            },
            "energy": {"type": "string", "enum": ["couch", "light", "moderate", "heavy"]},
            "weather": {"type": "string", "enum": ["any", "dry", "calm", "warm"]},
            "time": {"type": "string", "enum": ["lt-1hr", "half-day", "full-day", "multi-day"]},
            "blocked_parts": {"type": "boolean"},
        },
        "required": ["priority", "system", "location", "energy", "weather", "time", "blocked_parts"],
    },
}


def classify(title: str, body: str) -> list[str]:
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "apply_labels"},
        messages=[{
            "role": "user",
            "content": f"Title: {title}\n\nBody:\n{body or '(no body provided)'}",
        }],
    )

    for block in msg.content:
        if block.type == "tool_use" and block.name == "apply_labels":
            d = block.input
            labels = [
                d["priority"],
                f"sys:{d['system']}",
                f"energy:{d['energy']}",
                f"weather:{d['weather']}",
                f"time:{d['time']}",
            ]
            for loc in d["location"]:
                labels.append(f"loc:{loc}")
            if d.get("blocked_parts"):
                labels.append("blocked:parts")
            return labels
    return []


def main() -> None:
    title = os.environ["ISSUE_TITLE"]
    body = os.environ.get("ISSUE_BODY") or ""

    try:
        labels = classify(title, body)
    except Exception as exc:
        print(f"classification failed: {exc}", file=sys.stderr)
        labels = []

    output = ",".join(labels)
    print(f"labels: {output or '(none)'}")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"labels={output}\n")


if __name__ == "__main__":
    main()
