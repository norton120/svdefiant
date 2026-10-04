---
title: "Ready For Sea"
date: 2026-10-04T13:00:00Z
draft: true
summary: "The systems work that made departure actually possible"
---

Before the [jellyfish and mosquitos](/blog/escape) there were a few weeks of systems work that never made it into a post. Here's what actually got done in the final push before _Defiant_ left Windmill Marina.

### Electrical

Three items. First was pure safety: the two main DC bus bars behind the panel were sitting exposed and close together. If one broke loose underway and bridged the other, you'd know about it in the worst way. A few minutes with liquid tape in the appropriate colors fixed a problem that was embarrassing to have left open this long.

Second, the DC-DC charger. A Victron unit wired to feed the house bank from the starter battery while motoring. The alternator handles house charging in principle; the DC-DC gives it a reliable backbone, especially on longer passages where you're motoring through light air and need predictable charging. The breaker was on backorder for weeks, but the install was clean once it showed up.

Third, the ESP2 sensor node got a wiring overhaul. The fuel sender line had the wrong resistor, which produced readings that were wrong in creative ways. The deeper issue was topology: long signal runs in a noisy electrical environment just don't behave. The fix was to flip it — push 12v out to the edge over the long cable, drop to 5v with a buck converter at the sensor end, and run the sender contacts directly into the ESP2 there. This also sorted a hall effect sensor contact problem at the same time, which felt like found money.

### Plumbing

The Raritan Electroscan — the electropooper — needed a new electrode plate to function. Plate in, working head restored. That's one of those systems you notice only when it's gone.

The icebox was supposed to be a simple repair. Louie looked at it and declared the conversion unit dead, with no replacement parts available anywhere. I ended up waiting until early July for an Isotherm unit to come back in stock, then another week for it to arrive. Cold storage is now a thing on _Defiant_, which is more of an upgrade than it sounds after months without it.

The cockpit scupper was clogged. Cleared. Seems minor until you're in a squall and the cockpit is filling faster than it's draining.

### Canvas and cosmetics

The dinghy got sewn chaps to protect the hypalon from UV. Slow-moving problem with real consequences — hypalon doesn't recover from sun damage, and the dinghy is outside all day every day. Running light bases and the nameboard bung plugs got four coats of varnish, sanded between. And all the interior wood got a wipe-down with Murphy's Oil Soap, after which the cabin smelled genuinely good for about a week before the salt air got the final word.

---

With that batch closed out, _Defiant_ left Windmill in the best systems shape of her refit. We've been underway since late July, and the gremlins have been mercifully quiet so far.

<!-- closed-issues: #14, #34, #56, #81, #102, #112, #113, #118, #123 -->
