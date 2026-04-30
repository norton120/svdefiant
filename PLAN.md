# `defiant` CLI build plan

Handoff doc for the work begun in this session. Auto-memory carries the architecture decisions (`boat_state_architecture.md`, `ironclaw_cli_philosophy.md`); this file tracks **what's done and what's next**.

## Goal

Build a single CLI (`bin/defiant`) that the ironclaw agent on the Pi (older Qwen, paid Anthropic API tokens) uses for every operational action: read inbox, manage GitHub issues/project, search/edit wiki, get weather, read/write boat state. The CLI does the reasoning; the agent picks verbs.

## Why this shape (don't re-debate)

- Agent model is weak — narrow CLI verbs > MCP servers > raw `gh`/GraphQL/MCP calls.
- API-billed — every avoided re-parse is real money. Deterministic dedup (e.g. `inbox ack`) is the biggest single lever.
- Many systems beyond the agent need boat state — HA on the HAOS Pi is the canonical store; `defiant state` is a thin REST client (TOML stand-in for now, swap behind same surface).
- Pre-summarize everything. The agent matches strings (`weather:calm` is in `satisfies` array), never thresholds raw barometric pressure.

## CLI surface

| Noun | Verbs | Status |
|---|---|---|
| `state` | show / get / set / stale | ✅ done (TOML backend) |
| `inbox` | list / get / ack / unack | ✅ done (shells out to `scripts/inbox.py`) |
| `task` | list / show / create / update / close / iteration | ✅ done (wraps `gh` + Project v2 GraphQL) |
| `wiki` | search / show / edit | ⏳ stubbed |
| `weather` | (default) | ✅ done (OpenMeteo forecast + marine, NWS alerts, NOAA tides) |

State + ack files live under `DEFIANT_HOME` (default `~/.defiant`).

## Done

- **`bin/defiant`** — single uv-script entrypoint, subcommand dispatcher, atomic writes, schema validation. Smoke-tested locally.
- **`defiant state`** — TOML backed by `~/.defiant/state.toml`. Schema validates `mode.status` enum (`underway|anchored|moored|docked|hauled-out`), `location.lat/lon` as floats, `underway.eta` as ISO datetime. Auto-bumps `<section>.updated` on every `set`. `stale --max NNd|h|m` exits nonzero with per-section detail.
- **`defiant inbox`** — `list` defaults to `--unprocessed --since 14d`, filtered against `~/.defiant/inbox-state.json`. Matches messages by Message-ID *or* s3 key (whichever form the agent passes). `ack --note "<why>"` writes acked-at + note. `unack` reverses.
- **`defiant task`** — full verb set. `list` returns pre-summarized JSON (number/title/url/labels/milestone/state); `--schedulable` reads `mode.status` and drops `blocked:parts` always, drops `loc:dockside-only` unless docked, and when underway keeps only `loc:underway-ok`. `show <num>` adds body + project_status + iteration via one GraphQL round-trip. `create/update/close` port refit-task's idempotent dim-replace logic into Python (priority/sys/energy/weather/time replace any existing label in the same dim; loc replaces the whole `loc:*` set; `--blocked-parts`/`--no-blocked-parts` toggle). `iteration <num> --current|--next|--id` resolves the iteration via the cached field config and adds the issue to the project if missing. Smoke-tested locally end-to-end (create→update→show→iteration→close).
- **`defiant weather`** — direct API, no MCPs. Reads `state.location.lat/lon`. Pulls OpenMeteo daily forecast (wind kt, gusts, temp F, precip), OpenMeteo marine (waves m → ft), NWS active alerts (mapped to closed-vocab hazard tokens — anything unmapped is dropped). When `state.mode == underway` and `--no-tides` not set, finds nearest NOAA tide station via cached metadata (`~/.defiant/tide-stations.json`, 30d TTL, haversine, 100 km cap) and includes per-day high/low times. `satisfies` array derived per `plan-iteration` SKILL vocabulary (any / dry ≤20 kt / warm >65 °F / calm ≤10 kt + <2 ft + ≥40 °F). Smoke-tested against Annapolis (lat/lon → station 8575512).
- **Memories saved** (auto-memory): boat state architecture (HA canonical) + CLI philosophy. Indexed in `MEMORY.md`.

## Next steps (in order)

### 1. Deploy-blocker: new fine-grained PAT for the Pi

Local `gh` already has `project` scope so dev/test work fine. Before `defiant task` can run on ironclaw, the Pi needs a user-owned fine-grained PAT covering:
- `norton120/svdefiant`: Contents (RW for wiki repo), Issues (RW), Pull requests (RW), Metadata (R)
- Account: **Projects (RW)** — classic PATs cannot do this

After PAT is in place, retire the old one on the Pi.

### 2. `defiant wiki` — ripgrep, no embeddings

Wiki repo is already cloned on the Pi (per user). Path is TBD — figure out where on first run and add to `defiant` config or hardcode after confirmation.

- `wiki search <query> [--limit 5]` — ripgrep over the local clone, return ranked file list with snippets (file:line:context).
- `wiki show <page>` — print page content.
- `wiki edit <page> --body-file <path>` — replace, commit with mandated message format (`agent: <verb> <page>`), push. Enforce no-uncommitted-state on the Pi.

Don't build embeddings/FTS yet — ripgrep is sub-100ms for any reasonable wiki size.

### 3. Backend swap: `defiant state` TOML → HA REST

The user is doing HA setup in a parallel session: entities (`device_tracker.defiant`, `input_select.defiant_mode`, `input_text.defiant_destination`, `input_datetime.defiant_eta`, `binary_sensor.shore_power`), long-lived access token, automations.

Once the entities exist:

- Add HA config to `defiant`: `HA_URL`, `HA_TOKEN` env vars (or `~/.defiant/config.toml`).
- Replace `load_state()` / `save_state()` with REST calls (`GET /api/states/<entity>`, `POST /api/services/input_*/...`).
- Add cache: on read success, write through to `~/.defiant/state-cache.toml` with timestamp. On read failure, return cache and prepend `# WARNING: serving cached state from <ts>; HA unreachable` to stdout.
- On write failure: exit nonzero (do NOT silently write cache only — would desync).
- `defiant state stale` continues to work; freshness is now the `last_updated` field returned by HA per entity.

Callers (skills, scripts) shouldn't need to change — same CLI surface.

### 4. Migrate the existing skills

Strip raw `gh`/GraphQL out of:

- `.claude/skills/triage-deps/SKILL.md` — replace `scripts/inbox.py list` with `defiant inbox list`, replace `gh issue edit ...` with `defiant task update ...`. After triage, the agent should `defiant inbox ack <id>` for every email it processed.
- `.claude/skills/plan-iteration/SKILL.md` — replace the Project v2 GraphQL block (lines ~76–132) with `defiant task iteration <num> --current`. Replace the weather MCP usage with `defiant weather`. Replace location-asking with `defiant state get location` + `defiant state stale --max 3d`.

Also update `.github/scripts/triage-deps.py` (the workflow version) to call `defiant inbox` and ack what it processes — same dedup wins apply to the GitHub Action.

### 5. Deploy to the Pi

- Decide whether `defiant` lives in the repo (current: `bin/defiant`, gets deployed on `git pull`) or installs to `/usr/local/bin` via a small `install.sh`.
- AWS creds for SES bucket — confirm they're in `~/.aws/credentials` or env on ironclaw.
- Verify `uv` is installed on the Pi (script needs it for the inline shebang).
- Add `~/.defiant/` to a backup or sync if the ack history matters across reboots (probably yes).

## File map

- `bin/defiant` — the CLI
- `bin/refit-task` — legacy bash; will be absorbed by `defiant task`, don't delete yet
- `scripts/inbox.py` — SES reader; `defiant inbox` shells out to it. Keep importable shape.
- `.github/scripts/triage-deps.py` — runs the same logic as the workflow; consumes `scripts/inbox.py` directly. Update later.
- `.claude/skills/{triage-deps,plan-iteration}/SKILL.md` — rewrite to use `defiant` verbs.
- `.mcp.json` — currently registers `weather` and `noaa-tides` MCPs. After `defiant weather` lands, these should be removable (one less moving part on the Pi).

## Constraints / gotchas

- **Atomic writes** in `defiant`: write `.tmp` + `os.replace`. Already implemented; preserve when adding new state files.
- **State file does not embed inbox acks.** Boat state lives in `state.toml`/HA; ack history lives in `inbox-state.json`. Keep separate; they decay at different rates and have different consumers.
- **Schema additions:** when adding a new state key, update `SCHEMA` dict in `bin/defiant` and confirm the parallel HA entity exists. Don't let the two backends drift.
- **Mode-aware behavior must be CLI-side, not agent-side.** When `defiant weather` decides whether to include tides, `defiant task list --schedulable` decides what to filter — the agent should never need to know about `state.mode` to make those calls correctly.
- **The boat moves.** Don't bake location into config; `defiant state set location.name "..."` is the pattern. `state stale` warnings prevent stale-location footguns.

## Open questions

- **Wiki repo path** — proposal: `defiant wiki` auto-clones `https://github.com/norton120/svdefiant.wiki.git` to `~/.defiant/wiki` on first use, with `DEFIANT_WIKI` env var to override. User agreed in last session; not yet implemented.
- Should `defiant wiki edit` open a PR for the agent's commits, or commit directly? (Direct seems fine for now — wiki has no protected branches and the agent's changes are low-risk.)
- Is `bin/defiant` shipped to the Pi via `git pull`, or via a separate `install.sh` that copies to `/usr/local/bin`? Affects how venvs/deps are managed if we ever leave the uv-script model.

## Handoff for next session

What landed this session:
- `defiant state` (TOML), `defiant inbox` (SES), `defiant task` (gh + Project v2), `defiant weather` (OpenMeteo + NWS + NOAA tides) — all in `bin/defiant`, all smoke-tested locally.
- Auto-memory: `boat_state_architecture.md`, `ironclaw_cli_philosophy.md` (already indexed in `MEMORY.md`).

Pick-up order for next session (lowest-cost first):
1. **`defiant wiki`** — pure-local code, no auth needed for dev. Use ripgrep + `git`. See `### 2.` above.
2. **Migrate skills** — `triage-deps` and `plan-iteration` SKILL.md files. Mechanical edits to call `defiant` verbs.
3. **HA backend swap for `state`** — only when the user's HA entities are live. See `### 3.` above.
4. **Pi deploy** — needs the new fine-grained PAT (`### 1.`).

`bin/refit-task` is now fully superseded by `defiant task` but kept around — safe to delete after the skills are migrated and a real run confirms parity.

The two MCPs in `.mcp.json` (`weather`, `noaa-tides`) are now also superseded by `defiant weather` — safe to remove once the `plan-iteration` skill is migrated.
