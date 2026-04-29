---
name: plan-iteration
description: Interactively plan the upcoming iteration (sprint) for the S/V Defiant refit. Asks the user where the boat is, available days, energy level, and target milestone; pulls marine weather; filters open GitHub issues by their weather/time/energy/location labels; proposes a day-by-day plan; iterates with the user until approved; assigns chosen issues to the current iteration on GitHub Project #4. Use when the user asks to "plan the week", "plan the iteration", "what should we do this week", or similar.
---

# Plan iteration

Interactive sprint planner. Synthesizes weather forecast + filtered issues + user-stated capacity into a day-by-day plan.

## Always ask the user first

The boat moves. Don't assume location. Ask for:

1. **Location** — lat/lon, marina, or city. (Required for weather.)
2. **Days available this iteration** — which dates / how many.
3. **Energy level** — `couch`, `light`, `moderate`, or `heavy` (matches the `energy:*` labels).
4. **Target milestone** — one of: `Day Sails`, `Solomans`, `St. Michaels`, `NY`, `Annapolis`, `ICW Norfolk`, `Blue Water`. (If they don't know, suggest the milestone with the soonest open due date.)

## Steps

### 1. Marine weather forecast

Use the `weather` MCP for the location across the user's available days:
- `marine_conditions` for waves/swell/wind on the water
- `forecast` for precipitation, temperature, daily wind

For each day, derive a "weather profile" matching the repo's labels:
- **`weather:calm`** — light wind (≤10 kt), seas <2 ft, dry, mild
- **`weather:dry`** — no precipitation, wind ≤20 kt
- **`weather:warm`** — temp >65°F, dry
- **`weather:any`** — anything

A day "satisfies" a label if its profile is at-least that good. (e.g. `weather:calm` day satisfies `weather:any`, `weather:dry`, `weather:warm`, and `weather:calm`.)

### 2. Pull issues for the milestone

```
gh issue list --repo norton120/svdefiant --state open --milestone "<name>" --limit 300 --json number,title,labels,body
```

Exclude any with `blocked:parts`.

### 3. Filter by labels

For each issue, parse labels:
- `weather:*` — required weather (must be satisfied by the day)
- `time:lt-1hr` / `time:half-day` / `time:full-day` / `time:multi-day` — duration
- `energy:couch` / `energy:light` / `energy:moderate` / `energy:heavy` — required energy ≤ user's energy
- `loc:dockside-only` — only schedule when at a dock
- `loc:underway-ok` — schedulable on passage days
- `loc:aloft` / `loc:underwater` — extra weather caution; treat as `weather:calm` minimum even if not labeled as such
- `sys:*` — system grouping for context only

### 4. Build a day-by-day proposal

Match issues to days. Group multi-day issues across consecutive compatible days. Aim to:
- Fill larger time slots first
- Front-load harder work when energy is fresh (or per user preference)
- Group same-`sys:` issues when efficient
- Respect priority: `p0` > `p1` > `p2` > `p3`

Present as a table:

| Day | Date | Weather | Issues |
|-----|------|---------|--------|

Then ask: "Sound right? What would you change?"

### 5. Iterate

Adjust based on user feedback (swap issues, push to next iteration, add unlabeled work, etc.).

### 6. Commit to the project

Once the user approves, assign chosen issues to the **current iteration** on Project #4.

**Project IDs (cached):**
- Project: `PVT_kwHOAGJGHM4BVufn`
- Iteration field: `PVTIF_lAHOAGJGHM4BVufnzhRaGt0`

**Pre-flight check** — fetch the iteration field configuration:
```
gh api graphql -f query='{
  node(id: "PVTIF_lAHOAGJGHM4BVufnzhRaGt0") {
    ... on ProjectV2IterationField {
      configuration {
        duration
        iterations { id title startDate duration }
      }
    }
  }
}'
```

If `duration: 0` or `iterations: []`, the field hasn't been configured yet. Tell the user: "The Iteration field has no cadence set. Open https://github.com/users/norton120/projects/4/settings, set duration to 1 week starting your preferred Monday, then re-run me."

Otherwise, find the iteration whose `startDate ≤ today < startDate + duration`. That's the current iteration.

**For each chosen issue:**

1. Get the issue's project item ID (or add it to the project if not already there):
   ```
   gh api graphql -f query='{
     repository(owner:"norton120", name:"svdefiant") {
       issue(number: <N>) {
         projectItems(first: 5) {
           nodes { id project { id } }
         }
       }
     }
   }'
   ```
   Filter to the item whose `project.id == "PVT_kwHOAGJGHM4BVufn"`. If absent, add it:
   ```
   gh api graphql -f query='mutation {
     addProjectV2ItemById(input: {projectId: "PVT_kwHOAGJGHM4BVufn", contentId: "<issue node id>"}) {
       item { id }
     }
   }'
   ```

2. Set the iteration field value:
   ```
   gh api graphql -f query='mutation {
     updateProjectV2ItemFieldValue(input: {
       projectId: "PVT_kwHOAGJGHM4BVufn"
       itemId: "<item id>"
       fieldId: "PVTIF_lAHOAGJGHM4BVufnzhRaGt0"
       value: { iterationId: "<current iteration id>" }
     }) { projectV2Item { id } }
   }'
   ```

### 7. Final report

Confirm what was assigned, list issues that were considered but pushed out (with reasoning), and note any open questions for next iteration.

## Conservatism / safety

- If marine weather shows hazardous conditions on a `loc:underwater` or `loc:aloft` day, *flag it* and don't schedule those issues for that day even if all other constraints match.
- If the user provides energy `light` and an issue is labeled `energy:heavy`, do not schedule it; explain why.
- Be honest about uncertainty in forecast — Day 1-2 confident, day 5+ caveat.

## Notes

- Marine weather data has limited coastal accuracy (per the `weather` MCP's own warning). Use as planning input, not as a navigation/safety call.
- The `noaa-tides` MCP is also available if tide windows matter (e.g. ICW shoaling, bridge clearances).
