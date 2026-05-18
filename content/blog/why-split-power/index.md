---
title: "Why Split Power?"
summary: "The pros and cons of dual isolated power systems onboard"
cardimage: "power-bank.png"
date: 2026-05-17
draft: false
---

Long ago, _Defiant_ began her life with a pair of lead-acid deep cycle batteries. Even liveaboard electrical consumption was pretty trivial in 1989 - there were no laptops or phones constantly drinking juice, no AIS or Starlink. She didn't have autohelm or an electric windlass from the factory - so power needs more closely resembled a big car than a small floating house. As was the standard setup then, you had two batteries (main and backup) that started the motor, powered all the boat's energy needs, and recharged from the alternator. 

{{< figure src="stock.png" caption="standard 2 battery lead acid setup from the 1980's" >}}

When I inherited _Defiant_ the setup had shifted to a set of three carbon foam firefly batteries. These were still do-all power blocks that started the motor, supplied all the boat's systems, and charged from the alternator while the motor was running. But now the system was expanded to several solar panels and a wind generator that also charged these batteries (sort of). Carbon foam handles extreme temperatures better than lithium and discharges deeper than traditional lead acid, but the batteries are insanely heavy and bulky, and to get the power wall I needed half the cabin would have needed to be battery bricks. So I converted to Lithium.

{{< figure src="firefly.png" caption="these things were huge pigs. I fit 900ah of lithium in nearly the same space" >}}

One of the key changes I made was splitting the electrical into two completely independent systems:

- **lithium house bank** that powers the electronics, outlets, appliances, sensors, vessel management system etc.

- **Lead Acid Starter** that powers the engine starter motor, basic engine analogs (temp, oil pressure, alternator output) and charges from the engine's alternator when running. 

These systems have zero crossover. 

## So...Why Two Systems?

### Isolation

A diesel engine depleting a 100ah battery when the only load* is the starter is very unlikely. Even with a blown alternator, the starter battery would cover dozens, maybe even hundreds of starts - plenty of juice to limp for repairs. Household loads, on the other hand, can be both massive and mistake-prone. _Defiant_ could be crippled with her house power completely spent - no lights, running water, chart plotter or instruments - but still fire up the motor and limp into port without issue. On the flip side, I could find myself stranded with a dead starter battery even though I still have enough excess house juice for a week long *Murder, She Wrote* marathon.

{{< figure src="power-bank.png" caption="My home bank now lives inside completely independent from the lead acid starter under the quarterberth" >}}

### Lithium ≠ Lead Acid

Lead acid batteries were the standard power storage technology for the last hundred years. They have dependable characteristics in how they charge and discharge. Like most vessels of her era, all of _Defiant's_ original systems were designed with those characteristics in mind (especially her motor). The engineers of the mid 1980's only had to account for the one type of power source that could possibly be used in their systems - so they could hard-code the behaviors of lead acid batteries into everything they built. 

Lithium ion batteries do lots of things _very_ differently than lead acid. They have a completely different charge and discharge curve and operate at different peak voltages. The BMS in most LiFePO4 batteries will simply cut off power when the reserve gets too low - like how a modern cordless drill suddenly stops working when the battery is dead, instead of the slow loss of power found with older tools. Parts of the motor that are seemingly unrelated to the battery often expect, and count on, the slow voltage drop of a lead acid battery, or assume the peak voltage to be lower than the LiFePO4 will deliver. 

Shoving lithium where lead acid is expected won't flat-out fail, just like swapping a 13mm socket will sort-of work if you don't have a 1/2\" one lying around. It may undo the bolt once, but it will chew away the corners of the bolt head. Do it a few times and the bolt will be toast. Alternators expect a lead acid load to regulate. Battery tenders start protecting lead acid at 50% capacity - that's 40% higher than lithium. The list goes on. 

My motor expects a lead acid battery. So does Mike at NAPA if I need parts. So does every owner's manual, aftermarket part made before 2020, and forum post from the same era. Rather than spend the next 20 years translating and compensating and hoping I've made all the needed adjustments to convert a mid-90's tractor diesel to play nice with future-tech batteries, I opted for two distinct systems. 

### Reroute The EPS Coupling

Keeping the systems distinct also gives me that ever-present __Star Trek_ plot device as an emergency fallback - divert power from a secondary system to save the day. The 100ah LiFePO4 battery that powers the sanitation system could, in a pinch, be used to start the engine. So could any of the other nine LiFePO4s in the house bank. If stranded with a dead starter and no other options, I could rip apart my toilet and use it to jump the motor - but this only works because they are distinct power grids. 



### Critical Redundancy

I stated before that the only load on the starter battery is the starter, and that's not _technically_ true. I also have both bilge pumps wired directly to the starter battery at the moment. This is a temporary state, and eventually I will have dual-source relays feeding the pumps. Why? 



Bilge pumps are one of those things that need to function after every other thing has failed. If you are taking on water, they keep you alive. So I don't want to choose systems to draw from - in this case I want _both_ electrical grids to be available. My long term intent will be a relay between power blocks: under normal conditions the pumps are fed from the starter battery, but if that fails the relay cuts over to house power as the source. This not only gives me multiple levels of warning that something is wrong, but ensures that I use every possible resource to keep the boat afloat once we start taking on water. 




