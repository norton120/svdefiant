#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.0"]
# ///
"""defiant-mcp — stdio MCP server wrapping the `defiant` CLI.

Each defiant verb is exposed as a discrete MCP tool with a strict JSON schema.
Handlers shell out to ../bin/defiant; all credentials come from this process's
env (injected by ironclaw at spawn via `ironclaw mcp add … --env KEY=VAL`),
so the agent never sees raw tokens.

Register on ironclaw with:

    ironclaw mcp add defiant --transport stdio \\
      --command uv --arg run --arg --script \\
      --arg /home/ironclaw/app/svdefiant/scripts/defiant_mcp.py \\
      --env GH_TOKEN=… \\
      --env AWS_ACCESS_KEY_ID=… \\
      --env AWS_SECRET_ACCESS_KEY=… \\
      --env AWS_DEFAULT_REGION=us-east-1 \\
      --env HOME_ASSISTANT_ACCESS_TOKEN=…
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

DEFIANT = Path(__file__).resolve().parents[1] / "bin" / "defiant"
SUBPROCESS_TIMEOUT = 180  # seconds — wiki clone or HA-slow can take a while

# Closed-vocabulary enums mirror bin/defiant. Keeping them in sync is a manual
# step; if either side drifts, defiant will reject the bad value at coerce time.
PRIORITIES = ["p0", "p1", "p2", "p3"]
SYSTEMS = ["electrical", "rigging", "sails", "plumbing", "engine",
           "nav", "hull", "interior", "ground-tackle", "safety"]
LOCATIONS = ["indoors", "on-deck", "aloft", "underwater",
             "dockside-only", "underway-ok"]
ENERGIES = ["couch", "light", "moderate", "heavy"]
WEATHERS = ["any", "dry", "calm", "warm"]
TIMES = ["lt-1hr", "half-day", "full-day", "multi-day"]
MODES = ["underway", "anchored", "moored", "docked", "hauled-out"]
STATE_KEYS = [
    "location.name", "location.lat", "location.lon",
    "mode.status",
    "underway.destination", "underway.dest_lat", "underway.dest_lon", "underway.eta",
]


def _label_props() -> dict:
    """Common label-dimension args reused by task_create / task_update."""
    return {
        "priority": {"type": "string", "enum": PRIORITIES,
                     "description": "issue priority (replaces any prior p* label)"},
        "system": {"type": "string", "enum": SYSTEMS,
                   "description": "system category — sets sys:<value> (replaces any prior sys:*)"},
        "location": {"type": "array", "items": {"type": "string", "enum": LOCATIONS},
                     "description": "where the work happens — sets loc:<each>; replaces the full loc:* set"},
        "energy": {"type": "string", "enum": ENERGIES,
                   "description": "energy required — sets energy:<value> (replaces any prior energy:*)"},
        "weather": {"type": "string", "enum": WEATHERS,
                    "description": "weather floor — sets weather:<value> (replaces any prior weather:*)"},
        "time": {"type": "string", "enum": TIMES,
                 "description": "duration estimate — sets time:<value> (replaces any prior time:*)"},
    }


TOOLS: list[Tool] = [
    Tool(
        name="state_show",
        description="Show all boat state from Home Assistant (location, mode, underway sections). Falls back to ~/.defiant/state-cache.toml on HA error (warning included in output).",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="state_get",
        description="Get one state section or section.field, e.g. 'mode' or 'mode.status'.",
        inputSchema={
            "type": "object",
            "properties": {"key": {"type": "string", "description": "section or section.field"}},
            "required": ["key"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="state_set",
        description="Set one state field via HA service call. NOTE: location.lat/lon are auto-fed by SignalK every ~60s; manual writes only stick when SK is offline. mode.status is also auto-set by HA automations on shore-power and SoG > 1kt.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "enum": STATE_KEYS},
                "value": {"type": "string",
                          "description": "for mode.status, one of: " + ", ".join(MODES)},
            },
            "required": ["key", "value"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="state_stale",
        description="Check whether watched state sections (location, mode) are stale (older than 3 days). Output 'fresh' on success, '[exit 1] stale: <section> (...)' if any are stale. Use this to decide whether to ask the human to confirm location.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="inbox_list",
        description="List unprocessed inbound mail from the last 14 days (SES bucket). Filtered against ~/.defiant/inbox-state.json so previously-acked messages don't reappear. Returns JSON array of {message_id, s3_key, from, subject, date, snippet}. Filter the result yourself if you need a subset.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="inbox_get",
        description="Get the full body + headers of one inbound message by Message-ID or s3 key.",
        inputSchema={
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Message-ID or s3 key (substring ok)"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="inbox_ack",
        description="Mark a message processed; it won't appear in inbox_list again until unacked. ALWAYS ack messages you've decided about — even ones you decided weren't actionable — so they don't keep re-surfacing.",
        inputSchema={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="inbox_unack",
        description="Reverse a previous ack — message will reappear in inbox_list.",
        inputSchema={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_list",
        description="List open issues (norton120/svdefiant), pre-summarized as JSON. With schedulable=true, applies the boat-mode filter: drops blocked:parts always, drops loc:dockside-only unless docked, and (when underway) keeps only loc:underway-ok issues. With iteration set, restricts to that project iteration and adds iteration/day/project_status to each item.",
        inputSchema={
            "type": "object",
            "properties": {
                "milestone": {"type": "string", "description": "filter by milestone title"},
                "labels": {"type": "array", "items": {"type": "string"},
                           "description": "additional label filters (all-of when iteration is set, any-of otherwise)"},
                "limit": {"type": "integer", "default": 300},
                "with_body": {"type": "boolean", "default": False,
                              "description": "include the issue body in each item (large; only when matching/triage requires it)"},
                "schedulable": {"type": "boolean", "default": False,
                                "description": "apply boat-mode filter"},
                "iteration": {"type": "string",
                              "description": "'current', 'next', or a literal iteration id; restricts to that iteration and surfaces day/iteration/project_status"},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_show",
        description="Full issue details: body, labels, milestone, project status, current iteration. One GraphQL round-trip.",
        inputSchema={
            "type": "object",
            "properties": {"num": {"type": "integer"}},
            "required": ["num"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_create",
        description="Open a new issue with labels and add it to Project #4.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string", "description": "issue body (markdown)"},
                **_label_props(),
                "blocked_parts": {"type": "boolean", "default": False,
                                  "description": "add the blocked:parts label"},
                "milestone": {"type": "string",
                              "description": "milestone title (must already exist; use milestone_create first if not)"},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_update",
        description="Patch labels and/or body on an existing issue. Idempotent dim-replace: setting `priority` removes any prior p* label, `system` replaces any sys:*, `location` replaces the entire loc:* set. For milestone changes use task_set_milestone / task_clear_milestone; for parts blocking use task_block_parts / task_unblock_parts.",
        inputSchema={
            "type": "object",
            "properties": {
                "num": {"type": "integer"},
                "body": {"type": "string"},
                **_label_props(),
            },
            "required": ["num"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_block_parts",
        description="Add the blocked:parts label to an issue (it will be filtered out of schedulable lists). Idempotent.",
        inputSchema={
            "type": "object",
            "properties": {"num": {"type": "integer"}},
            "required": ["num"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_unblock_parts",
        description="Remove the blocked:parts label from an issue. Idempotent.",
        inputSchema={
            "type": "object",
            "properties": {"num": {"type": "integer"}},
            "required": ["num"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_set_milestone",
        description="Assign an issue to a milestone. The milestone must already exist (use milestone_create first if not). Replaces any prior milestone.",
        inputSchema={
            "type": "object",
            "properties": {
                "num": {"type": "integer"},
                "milestone": {"type": "string", "description": "milestone title"},
            },
            "required": ["num", "milestone"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_clear_milestone",
        description="Remove the milestone from an issue (the issue stays open).",
        inputSchema={
            "type": "object",
            "properties": {"num": {"type": "integer"}},
            "required": ["num"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="milestone_list",
        description="List GitHub milestones (norton120/svdefiant), pre-summarized as JSON: {number, title, state, description, due_on, open_issues, closed_issues, url}. Defaults to open milestones; pass state='all' to include closed.",
        inputSchema={
            "type": "object",
            "properties": {
                "state": {"type": "string", "enum": ["open", "closed", "all"],
                          "default": "open"},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="milestone_show",
        description="Show a single milestone, by number or exact title.",
        inputSchema={
            "type": "object",
            "properties": {
                "spec": {"type": "string",
                         "description": "milestone number or exact title"},
            },
            "required": ["spec"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="milestone_create",
        description="Create a new (open) milestone. Title must be unique in the repo. Due date is optional (YYYY-MM-DD or ISO datetime); description is optional markdown.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "due": {"type": "string",
                        "description": "YYYY-MM-DD or ISO datetime"},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="milestone_update",
        description="Patch a milestone (number or current title). Any subset of {title, description, due, state} updates only those fields. To remove a due date use milestone_clear_due. state ∈ {open, closed}.",
        inputSchema={
            "type": "object",
            "properties": {
                "spec": {"type": "string",
                         "description": "milestone number or current title"},
                "title": {"type": "string", "description": "new title"},
                "description": {"type": "string"},
                "due": {"type": "string",
                        "description": "YYYY-MM-DD or ISO datetime"},
                "state": {"type": "string", "enum": ["open", "closed"]},
            },
            "required": ["spec"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="milestone_clear_due",
        description="Remove the due date from a milestone.",
        inputSchema={
            "type": "object",
            "properties": {
                "spec": {"type": "string",
                         "description": "milestone number or current title"},
            },
            "required": ["spec"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="milestone_delete",
        description="Delete a milestone (irreversible). Issues previously in the milestone are not deleted, just unassigned. Use milestone_update state=closed if you want to retire a milestone non-destructively.",
        inputSchema={
            "type": "object",
            "properties": {
                "spec": {"type": "string",
                         "description": "milestone number or exact title"},
            },
            "required": ["spec"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_complete",
        description="Close an issue as completed (the work was finished). Use task_drop instead if the work won't be done.",
        inputSchema={
            "type": "object",
            "properties": {"num": {"type": "integer"}},
            "required": ["num"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_drop",
        description="Close an issue as not planned (the work won't be done — out of scope, no longer relevant, etc.). Use task_complete if the work was actually finished.",
        inputSchema={
            "type": "object",
            "properties": {"num": {"type": "integer"}},
            "required": ["num"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_iteration",
        description="Assign an issue to an iteration on Project #4. iteration='current' for this week, 'next' for the upcoming one, or a literal iteration id. Adds the issue to the project if it isn't already there.",
        inputSchema={
            "type": "object",
            "properties": {
                "num": {"type": "integer"},
                "iteration": {"type": "string",
                              "description": "'current', 'next', or a literal iteration id"},
            },
            "required": ["num", "iteration"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_day_set",
        description="Set the per-issue 'Target date' (the day the agent intends to do this work) on Project #4. Adds the issue to the project if it isn't already there.",
        inputSchema={
            "type": "object",
            "properties": {
                "num": {"type": "integer"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["num", "date"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_day_clear",
        description="Remove the per-issue 'Target date' on Project #4 (the issue stays in the project and iteration if previously assigned).",
        inputSchema={
            "type": "object",
            "properties": {"num": {"type": "integer"}},
            "required": ["num"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="calendar_add",
        description="Record a day-level event the agent should respect when scheduling (e.g. 'sailing', 'NYC for work'). One event per date — re-adding overwrites. Defaults to a blocking event (no work expected); pass soft=true for an FYI banner that doesn't block scheduling.",
        inputSchema={
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "label": {"type": "string", "description": "short event description"},
                "soft": {"type": "boolean", "default": False,
                         "description": "true → event shows on planner but does not block scheduling"},
            },
            "required": ["date", "label"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="calendar_remove",
        description="Remove the calendar event on a given date (no-op if none).",
        inputSchema={
            "type": "object",
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD"}},
            "required": ["date"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="calendar_list",
        description="List calendar events in a date window. Defaults to today + 7 days.",
        inputSchema={
            "type": "object",
            "properties": {
                "from_date": {"type": "string", "description": "YYYY-MM-DD (default: today)"},
                "to_date": {"type": "string", "description": "YYYY-MM-DD (default: today + 7d)"},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="cart_add",
        description=(
            "Add an Amazon product URL to a named virtual cart. The cart is just "
            "an ASIN list on disk — the agent never touches Amazon. When the user "
            "is ready, cart_get_url emits a click-to-checkout URL that populates "
            "their real Amazon cart for normal review/checkout. The server fetches "
            "the product page once for title/price. Same-ASIN re-add increments "
            "quantity. Cap is 40 unique items per cart; new carts are auto-created "
            "on first add."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": "Amazon product URL or short link (a.co/..., amzn.to/...). Use the canonical /dp/ URL after any variant selection — child ASIN, not parent."},
                "quantity": {"type": "integer", "default": 1, "minimum": 1},
                "cart": {"type": "string", "default": "stubb",
                         "description": "cart name; carts are persistent across sessions"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="cart_remove",
        description="Remove an ASIN from a cart.",
        inputSchema={
            "type": "object",
            "properties": {
                "asin": {"type": "string"},
                "cart": {"type": "string", "default": "stubb"},
            },
            "required": ["asin"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="cart_set_quantity",
        description="Set the quantity for an ASIN already in a cart. qty=0 removes the item.",
        inputSchema={
            "type": "object",
            "properties": {
                "asin": {"type": "string"},
                "qty": {"type": "integer", "minimum": 0},
                "cart": {"type": "string", "default": "stubb"},
            },
            "required": ["asin", "qty"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="cart_list",
        description="List items in a cart with titles, prices, per-item qty, and grand totals. Use this for the pre-checkout review.",
        inputSchema={
            "type": "object",
            "properties": {"cart": {"type": "string", "default": "stubb"}},
            "additionalProperties": False,
        },
    ),
    Tool(
        name="cart_list_names",
        description="List every named cart with item count, total qty, total price, and last-updated timestamp. Use this when the user references a cart loosely (e.g. 'the parts list I started last week') so you can pick the right name.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="cart_clear",
        description="Empty a cart. Explicit only — cart_get_url never auto-clears.",
        inputSchema={
            "type": "object",
            "properties": {"cart": {"type": "string", "default": "stubb"}},
            "additionalProperties": False,
        },
    ),
    Tool(
        name="cart_get_url",
        description="Emit the Amazon add-to-cart URL for a cart. When the user clicks (logged in to Amazon), the items appear in their real cart for normal review/checkout. Idempotent and non-destructive — the cart on disk is untouched, so you can re-emit the URL anytime.",
        inputSchema={
            "type": "object",
            "properties": {"cart": {"type": "string", "default": "stubb"}},
            "additionalProperties": False,
        },
    ),
    Tool(
        name="planner_publish",
        description="Render data/planner.json from the project iteration + calendar, commit, and push (drives the public planner page on svdefiant.com — CI rebuilds the site on push to main). Always includes per-day weather. No-op if data/planner.json is unchanged.",
        inputSchema={
            "type": "object",
            "properties": {
                "iteration": {"type": "string", "default": "current",
                              "description": "'current' (default), 'next', or a literal iteration id"},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="wiki_search",
        description="Regex search across the local wiki clone (smart-case: lowercase query is case-insensitive). Returns JSON array of {page, line, snippet}, snippets capped at 200 chars.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="wiki_show",
        description="Print a wiki page's content. `page` may be the bare name ('Engine') or include the .md suffix ('Engine.md').",
        inputSchema={
            "type": "object",
            "properties": {"page": {"type": "string"}},
            "required": ["page"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="wiki_edit",
        description="Replace a wiki page's contents and push. Refuses if the local wiki clone has uncommitted changes; pulls --ff-only first; commits as 'agent: <create|edit> <page>'. Pass body as a string; the wrapper writes the temp file.",
        inputSchema={
            "type": "object",
            "properties": {
                "page": {"type": "string"},
                "body": {"type": "string", "description": "new page body (markdown)"},
            },
            "required": ["page", "body"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="weather",
        description="7-day marine weather + tides for state.location. Tides are included automatically when state.mode == underway. Returns per-day {wind_kt_max, gust_kt_max, wave_ft_max, temp_f:[min,max], precip, satisfies:[any|dry|warm|calm], hazards:[NWS tokens]}. Match satisfies against issues' weather:* labels.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="image_add",
        description=(
            "Optimize a photo (resize to ≤2400px long-side, EXIF auto-orient, "
            "strip metadata, JPEG q85) and commit it to static/images/<name>.jpg "
            "on the main branch of norton120/svdefiant. CI rebuilds the site "
            "(~1-2 min), after which the image is hotlinkable at "
            "https://svdefiant.com/images/<name>.jpg — usable in wiki pages, "
            "GitHub issues, or Hugo {{< figure >}} shortcodes. Errors if an "
            "image with the same sanitized name already exists. Returns JSON "
            "{ok, filename, path, url, pushed}."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "filename stem (without extension). Sanitized to lowercase [a-z0-9._-]; spaces become hyphens. The '.jpg' extension is appended automatically.",
                },
                "data_base64": {
                    "type": "string",
                    "description": "raw image bytes, base64-encoded. Accepts jpg/jpeg/png/heic/heif/webp/gif/tiff source formats; output is always JPEG.",
                },
            },
            "required": ["name", "data_base64"],
            "additionalProperties": False,
        },
    ),
]


def _label_argv(args: dict) -> list[str]:
    out: list[str] = []
    if v := args.get("priority"): out += ["-p", v]
    if v := args.get("system"):   out += ["-s", v]
    if v := args.get("energy"):   out += ["-e", v]
    if v := args.get("weather"):  out += ["-w", v]
    if v := args.get("time"):     out += ["-t", v]
    if locs := args.get("location"):
        out += ["-l", ",".join(locs)]
    return out


def _build_argv(name: str, args: dict) -> tuple[list[str], list[Path]]:
    """Map MCP tool call → defiant argv. Returns (argv, tempfiles_to_clean)."""
    tmp: list[Path] = []

    def bodyfile(text: str) -> str:
        f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        f.write(text)
        f.close()
        tmp.append(Path(f.name))
        return f.name

    if name == "state_show":
        return ["state", "show"], tmp
    if name == "state_get":
        return ["state", "get", args["key"]], tmp
    if name == "state_set":
        return ["state", "set", args["key"], args["value"]], tmp
    if name == "state_stale":
        return ["state", "stale", "--max", "3d"], tmp

    if name == "inbox_list":
        return ["inbox", "list", "--since", "14d"], tmp
    if name == "inbox_get":
        return ["inbox", "get", args["id"]], tmp
    if name == "inbox_ack":
        return ["inbox", "ack", args["id"]], tmp
    if name == "inbox_unack":
        return ["inbox", "unack", args["id"]], tmp

    if name == "task_list":
        argv = ["task", "list", "--limit", str(args.get("limit", 300))]
        if v := args.get("milestone"):
            argv += ["--milestone", v]
        for lbl in args.get("labels") or []:
            argv += ["--label", lbl]
        if args.get("with_body"):
            argv.append("--with-body")
        if args.get("schedulable"):
            argv.append("--schedulable")
        if v := args.get("iteration"):
            argv += ["--iteration", v]
        return argv, tmp
    if name == "task_show":
        return ["task", "show", str(args["num"])], tmp
    if name == "task_create":
        argv = ["task", "create", args["title"]]
        argv += _label_argv(args)
        if v := args.get("body"):
            argv += ["--body-file", bodyfile(v)]
        if args.get("blocked_parts"):
            argv.append("--blocked-parts")
        if v := args.get("milestone"):
            argv += ["--milestone", v]
        return argv, tmp
    if name == "task_update":
        argv = ["task", "update", str(args["num"])]
        argv += _label_argv(args)
        if v := args.get("body"):
            argv += ["--body-file", bodyfile(v)]
        return argv, tmp
    if name == "task_block_parts":
        return ["task", "update", str(args["num"]), "--blocked-parts"], tmp
    if name == "task_unblock_parts":
        return ["task", "update", str(args["num"]), "--no-blocked-parts"], tmp
    if name == "task_set_milestone":
        return ["task", "update", str(args["num"]),
                "--milestone", args["milestone"]], tmp
    if name == "task_clear_milestone":
        return ["task", "update", str(args["num"]), "--no-milestone"], tmp
    if name == "task_complete":
        return ["task", "close", str(args["num"]), "--reason", "completed"], tmp
    if name == "task_drop":
        return ["task", "close", str(args["num"]), "--reason", "not planned"], tmp
    if name == "task_iteration":
        argv = ["task", "iteration", str(args["num"])]
        spec = args["iteration"]
        if spec == "current":
            argv.append("--current")
        elif spec == "next":
            argv.append("--next")
        else:
            argv += ["--id", spec]
        return argv, tmp
    if name == "task_day_set":
        return ["task", "day", str(args["num"]), args["date"]], tmp
    if name == "task_day_clear":
        return ["task", "day", str(args["num"]), "--clear"], tmp

    if name == "milestone_list":
        return ["milestone", "list", "--state", args.get("state", "open")], tmp
    if name == "milestone_show":
        return ["milestone", "show", args["spec"]], tmp
    if name == "milestone_create":
        argv = ["milestone", "create", args["title"]]
        if v := args.get("description"):
            argv += ["--description", v]
        if v := args.get("due"):
            argv += ["--due", v]
        return argv, tmp
    if name == "milestone_update":
        argv = ["milestone", "update", args["spec"]]
        if v := args.get("title"):
            argv += ["--title", v]
        if (v := args.get("description")) is not None:
            argv += ["--description", v]
        if v := args.get("due"):
            argv += ["--due", v]
        if v := args.get("state"):
            argv += ["--state", v]
        return argv, tmp
    if name == "milestone_clear_due":
        return ["milestone", "update", args["spec"], "--no-due"], tmp
    if name == "milestone_delete":
        return ["milestone", "delete", args["spec"]], tmp

    if name == "calendar_add":
        argv = ["calendar", "add", args["date"], args["label"]]
        if args.get("soft"):
            argv.append("--soft")
        return argv, tmp
    if name == "calendar_remove":
        return ["calendar", "remove", args["date"]], tmp
    if name == "calendar_list":
        argv = ["calendar", "list"]
        if v := args.get("from_date"):
            argv += ["--from", v]
        if v := args.get("to_date"):
            argv += ["--to", v]
        return argv, tmp

    if name == "cart_add":
        argv = ["cart", "add", args["url"],
                "--qty", str(args.get("quantity", 1))]
        if v := args.get("cart"):
            argv += ["--cart", v]
        return argv, tmp
    if name == "cart_remove":
        argv = ["cart", "remove", args["asin"]]
        if v := args.get("cart"):
            argv += ["--cart", v]
        return argv, tmp
    if name == "cart_set_quantity":
        argv = ["cart", "set-quantity", args["asin"], str(args["qty"])]
        if v := args.get("cart"):
            argv += ["--cart", v]
        return argv, tmp
    if name == "cart_list":
        argv = ["cart", "list"]
        if v := args.get("cart"):
            argv += ["--cart", v]
        return argv, tmp
    if name == "cart_list_names":
        return ["cart", "names"], tmp
    if name == "cart_clear":
        argv = ["cart", "clear"]
        if v := args.get("cart"):
            argv += ["--cart", v]
        return argv, tmp
    if name == "cart_get_url":
        argv = ["cart", "url"]
        if v := args.get("cart"):
            argv += ["--cart", v]
        return argv, tmp

    if name == "planner_publish":
        return ["planner", "publish",
                "--iteration", args.get("iteration", "current"),
                "--push"], tmp

    if name == "wiki_search":
        return ["wiki", "search", args["query"],
                "--limit", str(args.get("limit", 5))], tmp
    if name == "wiki_show":
        return ["wiki", "show", args["page"]], tmp
    if name == "wiki_edit":
        return ["wiki", "edit", args["page"],
                "--body-file", bodyfile(args["body"])], tmp

    if name == "weather":
        return ["weather", "--days", "7"], tmp

    if name == "image_add":
        try:
            data = base64.b64decode(args["data_base64"], validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"invalid base64 in data_base64: {e}")
        if not data:
            raise ValueError("data_base64 decoded to zero bytes")
        f = tempfile.NamedTemporaryFile("wb", suffix=".bin", delete=False)
        f.write(data)
        f.close()
        tmp.append(Path(f.name))
        return ["image", "add", args["name"], "--file", f.name], tmp

    raise ValueError(f"unknown tool: {name}")


def _child_env() -> dict[str, str]:
    """Build env for the bin/defiant subprocess. The CLI's shebang is
    `#!/usr/bin/env -S uv run --script`, so `uv` must be on PATH. systemd
    --user spawns ironclaw with a minimal PATH that often omits ~/.local/bin
    (the default uv install location); inject it defensively so the inner
    subprocess can resolve uv regardless of how this MCP server was launched.
    """
    env = os.environ.copy()
    extra = [str(Path.home() / ".local" / "bin"), "/usr/local/bin"]
    parts = env.get("PATH", "").split(":") if env.get("PATH") else []
    env["PATH"] = ":".join([p for p in extra if p not in parts] + parts)
    return env


def _run_defiant(argv: list[str]) -> tuple[str, str, int]:
    try:
        r = subprocess.run([str(DEFIANT), *argv],
                           capture_output=True, text=True,
                           timeout=SUBPROCESS_TIMEOUT, env=_child_env())
    except subprocess.TimeoutExpired as e:
        return "", f"defiant timed out after {SUBPROCESS_TIMEOUT}s: {e}", 124
    return r.stdout, r.stderr, r.returncode


server: Server = Server("defiant")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
    arguments = arguments or {}
    try:
        argv, tmp = _build_argv(name, arguments)
    except (KeyError, ValueError) as e:
        return [TextContent(type="text", text=f"error: bad arguments — {e}")]
    try:
        stdout, stderr, code = _run_defiant(argv)
    finally:
        for p in tmp:
            try:
                p.unlink()
            except OSError:
                pass

    if code != 0:
        msg = stderr.strip() or stdout.strip() or f"exit {code}"
        return [TextContent(type="text", text=f"[exit {code}] {msg}")]

    body = stdout.strip()
    if stderr.strip():
        # Surface defiant's stderr warnings (SK overwrite, HA cache fallback,
        # etc.) so the agent sees them.
        body = f"{body}\n\n[warnings]\n{stderr.strip()}" if body else f"[warnings]\n{stderr.strip()}"
    return [TextContent(type="text", text=body or "(no output)")]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="defiant",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
