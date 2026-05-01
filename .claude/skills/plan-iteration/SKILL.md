---
name: plan-iteration
description: Interactively plan the upcoming iteration (sprint) for the S/V Defiant refit. Pulls boat location and mode from Home Assistant via `defiant state`, marine weather from `defiant weather`, and schedulable open issues via `defiant task list --schedulable --with-body`; proposes a day-by-day plan; iterates with the user until approved; assigns chosen issues to the current iteration on GitHub Project #4 via `defiant task iteration`. Use when the user asks to "plan the week", "plan the iteration", "what should we do this week", or similar.
---

# Plan iteration

Interactive sprint planner. Synthesizes weather forecast + filtered issues + user-stated capacity into a day-by-day plan.

## Always confirm location and ask about capacity

The boat moves and HA may be stale. Run:

```
defiant state get location
defiant state stale --max 3d
```

- If `state stale` exits 0 (fresh): confirm with the user — "HA says we're at <name>. Still right?"
- If it exits nonzero (stale): ask the user where the boat actually is, then update HA so other tools stay in sync:
  ```
  defiant state set location.name "<name>"
  defiant state set location.lat <lat>
  defiant state set location.lon <lon>
  ```
  (Lat/lon are auto-fed by SignalK every ~60s, so manual lat/lon writes only stick if SK is offline. The CLI will warn.)

Then ask the user:

1. **Days available this iteration** — which dates / how many.
2. **Energy level** — `couch`, `light`, `moderate`, or `heavy` (matches the `energy:*` labels).
3. **Target milestone** — one of: `Day Sails`, `Solomans`, `St. Michaels`, `NY`, `Annapolis`, `ICW Norfolk`, `Blue Water`. (If they don't know, suggest the milestone with the soonest open due date.)

## Steps

### 1. Marine weather forecast

```
defiant weather --days <N>
```

Reads location and mode from `defiant state` automatically. For each day, `defiant weather` already returns:

- `wind_kt_max`, `gust_kt_max`, `wave_ft_max`, `temp_f`, `precip`, `hazards`
- `satisfies` array of weather labels the day meets — drawn from `{any, dry, warm, calm}`. A day with `satisfies: ["any","dry","warm","calm"]` is good for any weather-tagged issue; one with just `["any"]` is rough.

If `mode.status == underway`, tide entries are included automatically. Hazards (e.g. `gale_warning`, `small_craft_advisory`) come from NWS; treat any non-empty `hazards` list as a flag for `loc:aloft`/`loc:underwater`/`loc:on-deck` work that day.

### 2. Pull schedulable issues for the milestone

```
defiant task list --schedulable --milestone "<name>" --with-body
```

`--schedulable` already filters: drops `blocked:parts`, drops `loc:dockside-only` unless docked, and (when underway) keeps only `loc:underway-ok`. So you don't need to re-implement those rules.

### 3. Filter remaining dimensions per-day

For each issue, parse labels:
- `weather:*` — must be in the day's `satisfies` array
- `time:lt-1hr` / `half-day` / `full-day` / `multi-day` — duration
- `energy:couch` / `light` / `moderate` / `heavy` — required energy ≤ user's energy
- `loc:aloft` / `loc:underwater` — extra weather caution; require `weather:calm` in `satisfies` even if not labeled that strict
- `sys:*` — system grouping for context only

### 4. Build a day-by-day proposal

Match issues to days. Group multi-day issues across consecutive compatible days. Aim to:
- Fill larger time slots first
- Front-load harder work when energy is fresh (or per user preference)
- Group same-`sys:` issues when efficient
- Respect priority: `p0` > `p1` > `p2` > `p3`

Present as a table:

| Day | Date | Weather (`satisfies`) | Hazards | Issues |
|-----|------|----------------------|---------|--------|

Then ask: "Sound right? What would you change?"

### 5. Iterate

Adjust based on user feedback (swap issues, push to next iteration, add unlabeled work, etc.).

### 6. Commit to the project

Once the user approves, assign each chosen issue to the current iteration:

```
defiant task iteration <number> --current
```

`defiant task iteration` resolves the iteration via the cached project field config and adds the issue to the project if it isn't already there. If the iteration field has no cadence configured, the CLI will tell the user to open https://github.com/users/norton120/projects/4/settings.

To pre-stage an issue for the next iteration instead:

```
defiant task iteration <number> --next
```

### 7. Final report

Confirm what was assigned, list issues that were considered but pushed out (with reasoning), and note any open questions for next iteration.

## Conservatism / safety

- If `hazards` is non-empty for a day, *flag it* and don't schedule `loc:aloft` / `loc:underwater` / heavy on-deck issues for that day even if other constraints match.
- If the user provides energy `light` and an issue is labeled `energy:heavy`, do not schedule it; explain why.
- Be honest about uncertainty in forecast — Day 1-2 confident, day 5+ caveat.

## Notes

- `defiant weather` already includes tides when underway and skips them when not — the agent never has to reason about whether to fetch them.
- Marine wave data isn't available for inland points; the CLI sets a `marine_note` field when it falls back. Treat that as "wave height unknown" rather than "calm".
