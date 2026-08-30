---
title: "Last Pass"
date: 2026-08-30T13:00:00Z
draft: true
summary: "The unglamorous final sprint of work before Defiant finally cast off."
---

The departure story [already got told](/blog/escape). But boats don't just appear ready to sail — there's a brutal final sprint of work that has to happen first, and it rarely makes it into the polished narrative. Here's what the weeks before departure actually looked like.

### Electrical

The fuel sender setup had been wrong since I installed it. The ESP2 microcontroller was mounted too far from the tank, meaning the signal wires ran a long cable run that picked up enough noise to make the readings useless. The fix was to invert the design: move the ESP2 out to the tank edge, push 12V power out on the long run, and step it down with a buck converter right at the sensor. That also solved the contact problem I'd been having with the hall effect sensor out there. Swapped to a smaller resistor on the sender line while I was at it. Half a day of work, and the fuel gauge finally reads something I trust.

Got the Victron DC-DC charger wired in as well. This pulls from the starter battery and trickle-charges the house bank while the engine runs — a useful supplement to the alternator for keeping the LiFePO4s happy on longer motor passages.

There was also a p0 item I'd been avoiding looking at: the two big DC mains terminals behind the main panel were uncomfortably close together and exposed. If one worked loose underway and contacted the other, the result would be a very bad day. Coated both in liquid electrical tape, red and black respectively, so they can't bridge each other. Should have done it six months ago.

### Refrigeration and Plumbing

The icebox saga finally ended. The original compressor conversion couldn't be salvaged, and getting a replacement system meant waiting for Isotherm to come back into stock. Louie installed the new unit and we finally have a working refrigerator. Cold beer at anchor is no longer theoretical.

The electropooper also got its new electrode plate, which it had been patiently waiting on. Both ends of the sanitation situation are now functional.

While I was in the mood, I cleared the cockpit scupper line, which had been draining slowly for longer than I want to admit.

### Finishing Touches

Varnish got a final pass — running light bases and the bung plugs on the nameboards both had bare teak that would have suffered in the sun. Took four coats to get them sealed properly. Interior wood got a wipe-down with Murphy's Oil Soap, which made everything look dramatically better for almost no effort.

Sewed chaps for the dinghy to give the hypalon some UV protection now that we'll be in tropical sun indefinitely.

_Defiant_ is moving now. The punch list is closed. That feels stranger than I expected.

<!-- closed-issues: #123, #118, #113, #112, #102, #81, #56, #44, #34, #14 -->
