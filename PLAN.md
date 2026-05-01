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
| `state` | show / get / set / stale | ✅ done (HA REST backend, TOML cache fallback) |
| `inbox` | list / get / ack / unack | ✅ done (shells out to `scripts/inbox.py`) |
| `task` | list / show / create / update / close / iteration | ✅ done (wraps `gh` + Project v2 GraphQL) |
| `wiki` | search / show / edit | ✅ done (auto-clones; pure-Python search) |
| `weather` | (default) | ✅ done (OpenMeteo forecast + marine, NWS alerts, NOAA tides) |

State + ack files live under `DEFIANT_HOME` (default `~/.defiant`).

## Done

- **`bin/defiant`** — single uv-script entrypoint, subcommand dispatcher, atomic writes, schema validation. Smoke-tested locally.
- **`defiant state`** — HA REST backend reading the `defiant_*` helpers (see `boat_state_architecture.md` memory for entity layout). Read path: `GET /api/states/<eid>` → normalized dict shaped like the legacy TOML. Write path: per-entity `POST /api/services/<domain>/<service>` (single-key writes, no whole-dict replace). Cache: every successful read writes through to `~/.defiant/state-cache.toml`; on HA error, returns cache and prepends a `# WARNING: HA unreachable...` line on stderr. Write failures exit nonzero (no cache-only writes — would desync). Freshness: `<section>.updated` is the oldest `last_updated` of any entity in that section. `set location.lat/lon` warns about SK sync overwrite. Token: `HOME_ASSISTANT_ACCESS_TOKEN` env or repo `.env`.
- **`defiant inbox`** — `list` defaults to `--unprocessed --since 14d`, filtered against `~/.defiant/inbox-state.json`. Matches messages by Message-ID *or* s3 key (whichever form the agent passes). `ack --note "<why>"` writes acked-at + note. `unack` reverses.
- **`defiant task`** — full verb set. `list` returns pre-summarized JSON (number/title/url/labels/milestone/state); `--schedulable` reads `mode.status` and drops `blocked:parts` always, drops `loc:dockside-only` unless docked, and when underway keeps only `loc:underway-ok`. `show <num>` adds body + project_status + iteration via one GraphQL round-trip. `create/update/close` port refit-task's idempotent dim-replace logic into Python (priority/sys/energy/weather/time replace any existing label in the same dim; loc replaces the whole `loc:*` set; `--blocked-parts`/`--no-blocked-parts` toggle). `iteration <num> --current|--next|--id` resolves the iteration via the cached field config and adds the issue to the project if missing. Smoke-tested locally end-to-end (create→update→show→iteration→close).
- **`defiant weather`** — direct API, no MCPs. Reads `state.location.lat/lon`. Pulls OpenMeteo daily forecast (wind kt, gusts, temp F, precip), OpenMeteo marine (waves m → ft), NWS active alerts (mapped to closed-vocab hazard tokens — anything unmapped is dropped). When `state.mode == underway` and `--no-tides` not set, finds nearest NOAA tide station via cached metadata (`~/.defiant/tide-stations.json`, 30d TTL, haversine, 100 km cap) and includes per-day high/low times. `satisfies` array derived per `plan-iteration` SKILL vocabulary (any / dry ≤20 kt / warm >65 °F / calm ≤10 kt + <2 ft + ≥40 °F). Smoke-tested against Annapolis (lat/lon → station 8575512).
- **`defiant wiki`** — auto-clones `https://github.com/norton120/svdefiant.wiki.git` to `$DEFIANT_WIKI` or `~/.defiant/wiki` on first use. `search <query> [--limit 5]` is pure-Python `re` over `*.md` (smart-case: lowercase query → case-insensitive); returns ranked JSON `[{page, line, snippet}]`, snippets capped at 200 chars. `show <page>` prints contents (resolves `<page>` or `<page>.md`). `edit <page> --body-file <path>` refuses to run on a dirty tree, `git pull --ff-only`s, replaces the file, commits as `agent: <create|edit> <page>`, pushes. Search/show smoke-tested against the live wiki from this laptop; edit deliberately untested locally to avoid pushing to the real wiki — Pi will exercise it.
- **Memories saved** (auto-memory): boat state architecture (HA canonical) + CLI philosophy. Indexed in `MEMORY.md`.

## Next steps (in order)

### 1. Pi credentials — env-vars only, minimum scopes

Goal: no `gh auth login`, no `~/.aws/credentials`, no `gh auth setup-git`. All creds live in the agent's environment (e.g. `EnvironmentFile=` on the systemd unit, or the existing `.env` pattern), and `~/.defiant/` never holds anything sensitive.

**`GH_TOKEN`** — fine-grained PAT scoped to:
- Resource owner: your user (norton120)
- Repository access: only `norton120/svdefiant`
- Repository permissions:
  - **Contents: Read and write** (covers `git push` to the wiki, since the wiki shares the repo's Contents permission)
  - **Issues: Read and write** (`defiant task list/show/create/update/close`)
  - **Metadata: Read** (mandatory)
- Account permissions:
  - **Projects: Read and write** (`defiant task iteration` and project item-add)

No PR scope, no other repos, no Actions/Pages/etc. Both `gh` (via `GH_TOKEN`) and `defiant wiki edit` (via a one-shot `https://x-access-token:$GH_TOKEN@…` URL — token in subprocess argv only, never written to disk) pick this up automatically.

**AWS** — dedicated IAM user `defiant-ironclaw` with this inline policy (read-only on the inbound prefix, nothing else):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListInboundPrefix",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::svdefiant-inbound-mail",
      "Condition": { "StringLike": { "s3:prefix": ["inbound/*", "inbound"] } }
    },
    {
      "Sid": "GetInboundObjects",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::svdefiant-inbound-mail/inbound/*"
    }
  ]
}
```

Export `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION=us-east-1`. boto3 reads these natively; `~/.aws/` stays empty.

**Env vars the Pi agent needs** (full list):
```
HOME_ASSISTANT_ACCESS_TOKEN=...   # already in repo .env
HA_URL=http://homeassistant.local:8123   # optional; default works
GH_TOKEN=...                       # the new fine-grained PAT
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
DEFIANT_WIKI=...                   # optional; defaults to ~/.defiant/wiki
```

If the Pi already has a wiki clone elsewhere, set `DEFIANT_WIKI=<that path>` to skip the auto-clone.

### 2. Backend swap: `defiant state` TOML → HA REST — ✅ done

`bin/defiant` reads/writes HA helpers via REST. The vessel-side details (entity layout, automations, data flow) live on the [Vessel-Management-System wiki page](https://github.com/norton120/svdefiant/wiki/Vessel-Management-System).

CLI implementation notes:
- `STATE_ENTITIES` in `bin/defiant` maps dotted state keys → HA entity IDs.
- `_load_state_from_ha` writes through to `~/.defiant/state-cache.toml` on every successful read; `load_state` falls back to the cache (with `# WARNING: HA unreachable…` on stderr) when HA is unreachable, returns `{}` if both are unavailable.
- `cmd_state_set` writes a single entity per call (per-domain service / payload-key). Write failure exits non-zero; the cache is never written without a successful HA write (would desync).
- `cmd_state_stale` uses each entity's `last_updated` (oldest within a section).
- Token: `HOME_ASSISTANT_ACCESS_TOKEN` env or repo `.env`. Endpoint: `HA_URL` env (default `http://homeassistant.local:8123`).
- `set location.lat/lon` prints an SK-overwrite warning (auto-feed cadence ~60 s).

Open code follow-ups (not blockers):
- Expose SoG/CoG read-only via `defiant state` (e.g. a `nav` section computed from `sensor.defiant_signal_k_*`). Useful for `defiant weather --underway` decisions.
- Decide whether to gate manual lat/lon writes behind `--manual` (pauses the SK-sync automation). Right now the CLI just warns.

### 3. Migrate the existing skills — ✅ done

Both skills and the Action script now route through `defiant`:

- `.claude/skills/triage-deps/SKILL.md` — calls `defiant inbox list` (defaults to unprocessed via `~/.defiant/inbox-state.json`), `defiant task list --limit 300 --with-body`, `defiant task update <num> --blocked-parts | --no-blocked-parts`, and acks every processed email with `defiant inbox ack <id> --note "..."`.
- `.claude/skills/plan-iteration/SKILL.md` — pulls location/mode from `defiant state` (with `state stale --max 3d` to decide whether to confirm-or-ask the user), uses `defiant weather --days <N>` (returns `satisfies` and `hazards` per day directly — no client-side weather classification), `defiant task list --schedulable --milestone "<name>" --with-body`, and `defiant task iteration <num> --current` for project assignment.
- `.github/scripts/triage-deps.py` — uses `bin/defiant inbox list --since 14d --all` (CI runner is ephemeral so no persistent ack state; passes `--all` to match prior behavior) and `bin/defiant task update <num> --blocked-parts | --no-blocked-parts`. The workflow already installs `uv` so the script's shebang resolves cleanly.

`bin/defiant task list` gained `--with-body` to support these (off by default since body bloats the typical schedulable list output).

Open follow-up: persisting `~/.defiant/inbox-state.json` between Action runs (via `actions/cache`) would let the workflow drop `--all` and ack each processed email — saves Anthropic tokens. Not yet worth the complexity at current run cost.

### 4. Cleanup — ✅ done

- `bin/refit-task` deleted (fully superseded by `defiant task`).
- `.mcp.json` deleted (only registered `weather` + `noaa-tides`, both superseded by `defiant weather`). Restore the file if a future MCP is needed.

### 5. Wire `defiant` into ironclaw via stdio MCP

The ironclaw agent itself is sandboxed from secrets — its built-in shell tool scrubs `*_TOKEN` / `*_KEY` / `*_SECRET` / `*_PASSWORD` before exec, and WASM tools auth via the host's network proxy (no Bearer-type fit for AWS sigv4). The path that matches is **stdio MCP**: ironclaw spawns the MCP server process with env vars passed via `--env`, those vars come from ironclaw's encrypted secrets store, and the agent only sees the MCP tool surface.

`scripts/defiant_mcp.py` is that server — a stdio MCP wrapper around `bin/defiant`. 18 tools (`state_show`/`get`/`set`/`stale`, `inbox_list`/`get`/`ack`/`unack`, `task_list`/`show`/`create`/`update`/`close`/`iteration`, `wiki_search`/`show`/`edit`, `weather`), each with strict JSON schemas. Handlers shell out to the CLI; `body` strings for `task_create`/`task_update`/`wiki_edit` are written to ephemeral tempfiles internally so the agent never deals with file plumbing. Stderr warnings (HA cache fallback, SK overwrite) are surfaced as `[warnings]` blocks in the tool result so the agent can react. Smoke-tested locally end-to-end via the MCP protocol.

Register on ironclaw:

```sh
ironclaw mcp add defiant --transport stdio \
  --command uv --arg run --arg --script \
  --arg /home/ironclaw/app/svdefiant/scripts/defiant_mcp.py \
  --env GH_TOKEN=… \
  --env AWS_ACCESS_KEY_ID=… \
  --env AWS_SECRET_ACCESS_KEY=… \
  --env AWS_DEFAULT_REGION=us-east-1 \
  --env HOME_ASSISTANT_ACCESS_TOKEN=…
```

The values go into ironclaw's secrets store; rotate with `ironclaw mcp remove defiant && ironclaw mcp add defiant …`.

After verification, remove the now-redundant built-in `github` WASM tool: `ironclaw tool uninstall github`. `defiant`'s task verbs cover everything the agent used it for, and consolidating reduces the live tool surface (fewer "which tool do I pick" failures from a weak agent).

Other deploy items:
- Verify `uv` is installed on the Pi (`scripts/defiant_mcp.py` and `bin/defiant` both use `uv run --script` shebangs).
- `~/.defiant/inbox-state.json` survives reboots (homedirs aren't tmpfs); no backup wiring needed unless you reprovision the Pi from scratch.
- `bin/defiant` ships via the existing `git pull` of the svdefiant repo on ironclaw — no separate install step.

## File map

- `bin/defiant` — the CLI
- `scripts/defiant_mcp.py` — stdio MCP wrapper for ironclaw (18 tools)
- `scripts/inbox.py` — SES reader; `defiant inbox` shells out to it. Keep importable shape.
- `.github/scripts/triage-deps.py` — runs the same logic as the workflow; calls `defiant` verbs.
- `.claude/skills/{triage-deps,plan-iteration}/SKILL.md` — `defiant`-only.

## Constraints / gotchas

- **Atomic writes** in `defiant`: write `.tmp` + `os.replace`. Already implemented; preserve when adding new state files.
- **State file does not embed inbox acks.** Boat state lives in `state.toml`/HA; ack history lives in `inbox-state.json`. Keep separate; they decay at different rates and have different consumers.
- **Schema additions:** when adding a new state key, update `SCHEMA` dict in `bin/defiant` and confirm the parallel HA entity exists. Don't let the two backends drift.
- **Mode-aware behavior must be CLI-side, not agent-side.** When `defiant weather` decides whether to include tides, `defiant task list --schedulable` decides what to filter — the agent should never need to know about `state.mode` to make those calls correctly.
- **The boat moves.** Don't bake location into config; `defiant state set location.name "..."` is the pattern. `state stale` warnings prevent stale-location footguns.

## Open questions

- Is `bin/defiant` shipped to the Pi via `git pull`, or via a separate `install.sh` that copies to `/usr/local/bin`? Affects how venvs/deps are managed if we ever leave the uv-script model.
- `defiant wiki edit` commits directly to `master` (no PR). Wiki has no protected branches and agent commits are low-risk; revisit if the agent ever starts making wide-radius changes.

## Handoff for next session

Local side is done. CLI feature-complete, both skills + the Action route through `defiant`, the stdio MCP shim is built and protocol-tested, classic PAT scopes are documented, the dedicated `defiant-ironclaw` IAM user is created with its keys at `secrets/ironclaw.env`.

## Overnight deploy — ✅ done

Everything below is verified on the Pi. Two unattended verifications skipped (need agent + model billing): a real LLM-driven tool call, and exercising write paths like `task_create` / `wiki_edit` (we don't write test issues / wiki edits unsupervised).

### What landed on the Pi

- Repo cloned at `/home/ironclaw/Repos/svdefiant` from origin.
- `uv` 0.11.8 installed at `/home/ironclaw/.local/bin/uv` (user-scoped, no sudo).
- `gh` CLI 2.92.0 installed at `/home/ironclaw/.local/bin/gh` (downloaded the static binary from the official release; no apt repo touched, no sudo).
- `~/.defiant/state-cache.toml` and `~/.defiant/wiki/` (auto-created on first run).
- No system services touched. No `~/.aws/`, no `gh auth login`, no `gh auth setup-git`. No changes to `~/.ironclaw/`, postgres, tailscale, systemd units, or anywhere else outside `/home/ironclaw/{Repos,.local,.defiant}`.

### MCP server registered with ironclaw

```
ironclaw mcp add defiant --transport stdio \
  --command /home/ironclaw/.local/bin/uv \
  --arg run --arg=--script \
  --arg /home/ironclaw/Repos/svdefiant/scripts/defiant_mcp.py \
  --env GH_TOKEN=… \
  --env AWS_ACCESS_KEY_ID=… \
  --env AWS_SECRET_ACCESS_KEY=… \
  --env AWS_DEFAULT_REGION=us-east-1 \
  --env HOME_ASSISTANT_ACCESS_TOKEN=… \
  --description "S/V Defiant operational CLI: HA state, SES inbox, GitHub issues+project, weather, wiki"
```

(Note `--arg=--script` — clap rejects `--arg --script` because `--script` looks like a flag. The `=` form binds it as a value.)

`ironclaw mcp list --verbose` shows: defiant registered, all 5 env keys stored (GH_TOKEN, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION, HOME_ASSISTANT_ACCESS_TOKEN). `ironclaw mcp test defiant` returns `Connection successful! Available tools (18)`.

### Smoke-tested through the MCP server (Pi-side, with the same env values ironclaw will inject):

| Tool | Result |
|---|---|
| `state_show` | OK — returned live HA state (Windmill Point Marina) |
| `state_stale` | OK |
| `task_list` (limit 3) | OK — returned 3 issues |
| `task_show 1` | OK — body, labels, project_status, iteration |
| `inbox_list` | OK — 1 SES message back |
| `weather` (1 day) | OK — full forecast + satisfies + hazards |
| `wiki_search` | OK — wiki auto-cloned on first call |

### Code patches that landed during deploy (already committed + pushed)

- `scripts/defiant_mcp.py` — defensively prepend `~/.local/bin` (and `/usr/local/bin`) to `PATH` for the `bin/defiant` subprocess. systemd `--user` services and ironclaw's spawn env don't include those by default; without this fix the inner `env uv` shebang lookup fails.
- `bin/defiant` — replace `gh project item-add` calls in `cmd_task_create` and `cmd_task_update` with the existing GraphQL `_ensure_project_item` helper. The `gh project` subcommand requires `read:org` on the PAT (gh dispatches via an org-aware codepath even for user-owned projects); raw GraphQL `addProjectV2ItemById` only needs the `project` scope. Lets the PAT stay at the documented `public_repo + project` minimum.

### Morning verifications (need a human)

1. **Real agent invocation** — ask the agent (via gateway/telegram) something like *"What's the boat state and what should I work on today?"* — that exercises HA + GitHub + weather through ironclaw's actual secret injection. If it works, the loop is closed.
2. **Write paths** — try `task_create` / `task_update` via the agent on a test issue, or with a dry comment. The read tests passed, and the write code uses the same gh + GraphQL underneath, but a human-witnessed write is the real proof.
3. **Optional**: `ironclaw tool uninstall github` once you're satisfied with `task_*` parity. The github WASM tool is intentionally left installed tonight so the agent has a fallback if the MCP path hits a snag.

### Things to know if something's off

- MCP server logs go to ironclaw's logs (subprocess stdout/stderr is captured by ironclaw). To poke at it manually, `bash -c 'export GH_TOKEN=…; export …; /home/ironclaw/.local/bin/uv run --script /home/ironclaw/Repos/svdefiant/scripts/defiant_mcp.py'` and feed it JSON-RPC over stdin.
- To rotate any secret: `ironclaw mcp remove defiant && ironclaw mcp add defiant …` with the new value.
- `~/.bashrc` early-returns for non-interactive shells, so the user-set `GH_TOKEN` / `AWS_*` exports there don't reach systemd-spawned processes. Doesn't matter — ironclaw's secret store handles that for the MCP subprocess. But if you ever need those vars in another systemd unit, use `~/.config/environment.d/` instead.
