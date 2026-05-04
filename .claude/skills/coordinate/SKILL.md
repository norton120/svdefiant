---
name: coordinate
description: Continuously re-coordinates the S/V Defiant work map (issues × Target dates × milestones) against the rolling window of weather, boat state, and parts blockers. Pulls boat location/mode from Home Assistant via `defiant state`, marine weather from `defiant weather`, the current scheduled work via `defiant task list --in-window`, the slipped pile via `--overdue`, and the candidate bench via `defiant task list --schedulable --unscheduled --with-body`. Proposes and applies adjustments — bump dates, pull from bench, clear stale dates — then republishes the planner. Runs every time the picture needs an update; not a sprint ceremony. Use when the user asks to "replan", "coordinate", "rework the plan", "what should I do this week", or after weather/parts/state changes.
---

# Coordinate

Continuously re-aligns the work map. The agent's job each run: look at what's scheduled, what slipped, what's available, and what's coming weather-wise, and adjust Target dates so the next 7 days reflect reality.

This is **not** a once-per-sprint ritual. Run it whenever the picture changes — weather shifts, parts arrive, the boat moves, an item slipped. Each run only needs to make the *deltas* better; you don't have to start from a blank sheet.

## Mental model

- **Long horizon = milestones.** GitHub milestones (`Day Sails`, `Solomans`, `St. Michaels`, `NY`, `Annapolis`, `ICW Norfolk`, `Blue Water`) carry the multi-week goals. They are the only "where are we headed" container.
- **Short horizon = Target date.** Each issue's per-issue Target date is the only thing that determines what shows on the planner page. There is no iteration container.
- **The bench.** Issues with priority + system + estimate but no Target date are the candidate pool — pulled in as window slots open.
- **The deep backlog.** Issues with Target dates far in the future (months / years out) are deliberate long-horizon scheduling, not stale data. The refit captures *everything* — some of it the user won't get to for years. Move these freely when there's a reason (pull forward into capacity, push back when something slips, milestone reshuffle), but don't churn dates that are working fine just to "tidy up."

## Always confirm location and ask about capacity

The boat moves and HA may be stale. Run:

```
defiant state get location
defiant state stale --max 3d
```

- If `state stale` exits 0 (fresh): confirm with the user — "HA says we're at <name>. Still right?"
- If it exits nonzero (stale): ask where the boat actually is, then update HA so other tools stay in sync:
  ```
  defiant state set location.name "<name>"
  defiant state set location.lat <lat>
  defiant state set location.lon <lon>
  ```
  (Lat/lon are auto-fed by SignalK every ~60s, so manual lat/lon writes only stick if SK is offline. The CLI will warn.)

Then ask the user:

1. **Energy level for the next few days** — `couch`, `light`, `moderate`, `heavy` (matches `energy:*` labels). Defaults to whatever you used last run if they don't say.
2. **Target milestone** — usually unchanged from prior runs; only ask if it isn't obvious.

## Steps

### 1. Read current state

```
defiant weather --days 7
defiant task list --in-window 7        # what's already scheduled
defiant task list --overdue            # what slipped
defiant milestone show "<active>"      # progress / due date
```

`defiant weather` returns per-day `satisfies` arrays drawn from `{any, dry, warm, calm}`. A day with `satisfies: ["any","dry","warm","calm"]` is good for any weather-tagged issue; just `["any"]` is rough. Treat non-empty `hazards` (e.g. `gale_warning`, `small_craft_advisory`) as a flag against `loc:aloft` / `loc:underwater` / `loc:on-deck` work that day.

### 2. Read the bench

```
defiant task list --schedulable --unscheduled --milestone "<name>" --with-body
```

`--schedulable` already filters: drops `blocked:parts`, drops `loc:dockside-only` unless docked, and (when underway) keeps only `loc:underway-ok`. `--unscheduled` keeps only items with no Target date — the genuine candidate pool.

### 3. Compute the deltas

For each day in the window, you have:
- weather (`satisfies`, `hazards`)
- already-scheduled items (from `--in-window`)

For each candidate issue, parse labels:
- `weather:*` — must be in the day's `satisfies` array
- `time:lt-1hr` / `half-day` / `full-day` / `multi-day` — duration
- `energy:couch` / `light` / `moderate` / `heavy` — required ≤ user's energy
- `loc:aloft` / `loc:underwater` — require `calm` in `satisfies` regardless of label
- `sys:*` — system grouping; cluster same-system items when efficient

Decide adjustments:

- **Overdue items** — bump to the next day they fit, or surface to the user if they need to clear/drop them.
- **Items dated to the wrong day** (e.g. `weather:warm` on a cold front day) — bump to a fitting day.
- **Empty / under-filled days** — pull the highest-priority candidate that fits. Candidates are the bench (no Target date) AND deep-backlog items (dated far out) when their priority/fit warrants pulling forward.
- **Crowded days** — push the lowest-priority overflow back to the bench (`task day --clear`) or to a later in-window day. Pushing in-window items further out (deep backlog) is fine when warranted by milestone shape.
- **Milestone slip risk** — if the active milestone has a due date and the work in/before that date doesn't fit, flag it; reshuffle deep-backlog dates to align.

Don't churn dates for the sake of churn. Moving a 2027 item by a week with no underlying reason is noise — leave it. Move when weather, parts, slip, or milestone shape gives you a reason.

Present as a diff-style proposal:

| Action | Issue | From → To | Why |
|--------|-------|-----------|-----|

Then ask: "Apply these? Anything you want to override?"

### 4. Iterate with the user

Swap, defer, drop. Quick.

### 5. Apply

For each approved change:

```
defiant task day <number> <YYYY-MM-DD>     # set or change Target date
defiant task day <number> --clear          # send back to the bench
```

Both are idempotent and add the issue to the project if it isn't already there.

### 6. Republish

```
defiant planner publish --push
```

This rebuilds `data/planner.json` from the now-updated Target dates and pushes; CI rebuilds the public planner page.

### 7. Final report

One-paragraph summary: scheduled / unscheduled / pushed / dropped, plus any open questions or risks for next run.

## Conservatism / safety

- If `hazards` is non-empty for a day, *flag it* and don't schedule `loc:aloft` / `loc:underwater` / heavy on-deck items for that day even if other labels match.
- If the user said `light` energy and an issue is labeled `energy:heavy`, don't schedule it; explain why.
- Day 1–2 forecast: confident. Day 5+: caveat — these placements may rebump on the next run.
- Never silently drop an item from the plan. If something doesn't fit, either it goes back to the bench (`task day --clear`) or it gets dropped from the milestone explicitly with the user's say-so (`task close --reason "not planned"`).

## Notes

- `defiant weather` includes tides when underway and skips them otherwise — agent doesn't reason about that.
- Marine wave data isn't available inland; the CLI sets a `marine_note` when it falls back. Treat as "wave unknown" not "calm".
- The public planner page only renders items dated inside the rolling window — it is operational, not a backlog browser. To see slipped or unscheduled work, use `defiant task list --overdue` / `--unscheduled`. To see the deep backlog, use the GitHub Project directly.
