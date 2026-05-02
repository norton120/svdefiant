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
        description="Check whether watched state sections (location, mode) are stale. Output 'fresh' on success, '[exit 1] stale: <section> (...)' if any are older than max. Use this to decide whether to ask the human to confirm location.",
        inputSchema={
            "type": "object",
            "properties": {"max": {"type": "string", "default": "3d",
                                    "description": "max age, e.g. '3d', '12h', '30m'"}},
            "additionalProperties": False,
        },
    ),
    Tool(
        name="inbox_list",
        description="List inbound mail (SES bucket). Defaults to unprocessed messages from the last 14 days, filtered against ~/.defiant/inbox-state.json so previously-acked messages don't reappear. Returns JSON array of {message_id, s3_key, from, subject, date, snippet}.",
        inputSchema={
            "type": "object",
            "properties": {
                "since": {"type": "string", "default": "14d",
                          "description": "lookback window, NNd|NNh|NNm"},
                "from_pattern": {"type": "string", "description": "regex on the From header"},
                "subject_pattern": {"type": "string", "description": "regex on the Subject line"},
                "include_acked": {"type": "boolean", "default": False,
                                  "description": "include previously-acked messages"},
            },
            "additionalProperties": False,
        },
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
            "properties": {
                "id": {"type": "string"},
                "note": {"type": "string", "description": "one-line reason for the ack (debug aid)"},
            },
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
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_update",
        description="Patch labels and/or body on an existing issue. Idempotent dim-replace: setting `priority` removes any prior p* label, `system` replaces any sys:*, `location` replaces the entire loc:* set. blocked_parts is tri-state (omit / true=add / false=remove).",
        inputSchema={
            "type": "object",
            "properties": {
                "num": {"type": "integer"},
                "body": {"type": "string"},
                **_label_props(),
                "blocked_parts": {"type": "boolean",
                                  "description": "true → add blocked:parts; false → remove; omit → no change"},
            },
            "required": ["num"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="task_close",
        description="Close an issue.",
        inputSchema={
            "type": "object",
            "properties": {
                "num": {"type": "integer"},
                "reason": {"type": "string", "enum": ["completed", "not planned"]},
            },
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
        name="task_day",
        description="Set or clear the per-issue 'Target date' (the day the agent intends to do this work) on Project #4. Pass date='YYYY-MM-DD' to set, or clear=true to remove. Adds the issue to the project if it isn't already there.",
        inputSchema={
            "type": "object",
            "properties": {
                "num": {"type": "integer"},
                "date": {"type": "string",
                         "description": "YYYY-MM-DD; mutually exclusive with clear"},
                "clear": {"type": "boolean", "default": False,
                          "description": "true → remove the day from this issue"},
            },
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
        name="planner_publish",
        description="Render data/planner.json from the project iteration + calendar (drives the public planner page on svdefiant.com). Optionally commits and pushes; CI rebuilds the site on merge to main. Use commit=true after a re-plan; otherwise omit and just verify the JSON before pushing.",
        inputSchema={
            "type": "object",
            "properties": {
                "iteration": {"type": "string", "default": "current",
                              "description": "'current' (default), 'next', or a literal iteration id"},
                "commit": {"type": "boolean", "default": False,
                           "description": "git add + commit data/planner.json after writing"},
                "push": {"type": "boolean", "default": False,
                         "description": "implies commit; also git push (triggers a site rebuild)"},
                "no_weather": {"type": "boolean", "default": False,
                               "description": "skip per-day weather fetch (e.g. offline)"},
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
        description="Marine weather + tides for state.location. Tides included automatically when state.mode == underway. Returns per-day {wind_kt_max, gust_kt_max, wave_ft_max, temp_f:[min,max], precip, satisfies:[any|dry|warm|calm], hazards:[NWS tokens]}. Match satisfies against issues' weather:* labels.",
        inputSchema={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 7,
                         "description": "forecast horizon, 1-16"},
                "no_tides": {"type": "boolean", "default": False,
                             "description": "omit tides even when underway"},
            },
            "additionalProperties": False,
        },
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
        return ["state", "stale", "--max", args.get("max", "3d")], tmp

    if name == "inbox_list":
        argv = ["inbox", "list", "--since", args.get("since", "14d")]
        if args.get("include_acked"):
            argv.append("--all")
        if v := args.get("from_pattern"):
            argv += ["--from", v]
        if v := args.get("subject_pattern"):
            argv += ["--subject", v]
        return argv, tmp
    if name == "inbox_get":
        return ["inbox", "get", args["id"]], tmp
    if name == "inbox_ack":
        argv = ["inbox", "ack", args["id"]]
        if v := args.get("note"):
            argv += ["--note", v]
        return argv, tmp
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
        return argv, tmp
    if name == "task_update":
        argv = ["task", "update", str(args["num"])]
        argv += _label_argv(args)
        if v := args.get("body"):
            argv += ["--body-file", bodyfile(v)]
        bp = args.get("blocked_parts")
        if bp is True:
            argv.append("--blocked-parts")
        elif bp is False:
            argv.append("--no-blocked-parts")
        return argv, tmp
    if name == "task_close":
        argv = ["task", "close", str(args["num"])]
        if v := args.get("reason"):
            argv += ["--reason", v]
        return argv, tmp
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
    if name == "task_day":
        argv = ["task", "day", str(args["num"])]
        if args.get("clear"):
            argv.append("--clear")
        elif v := args.get("date"):
            argv.append(v)
        else:
            raise ValueError("task_day requires either date or clear=true")
        return argv, tmp

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

    if name == "planner_publish":
        argv = ["planner", "publish",
                "--iteration", args.get("iteration", "current")]
        if args.get("push"):
            argv.append("--push")
        elif args.get("commit"):
            argv.append("--commit")
        if args.get("no_weather"):
            argv.append("--no-weather")
        return argv, tmp

    if name == "wiki_search":
        return ["wiki", "search", args["query"],
                "--limit", str(args.get("limit", 5))], tmp
    if name == "wiki_show":
        return ["wiki", "show", args["page"]], tmp
    if name == "wiki_edit":
        return ["wiki", "edit", args["page"],
                "--body-file", bodyfile(args["body"])], tmp

    if name == "weather":
        argv = ["weather", "--days", str(args.get("days", 7))]
        if args.get("no_tides"):
            argv.append("--no-tides")
        return argv, tmp

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
