---
title: "Jimmy Shower"
subtitle: "Cleaning up like a human being while living onboard :shower:"
date: 2026-04-03T16:40:24Z
draft: false
summary: "Turning a gallon of fresh water and 100Wh into a hot, every-day shower."
cardimage: images/jimmy-shower/image13.png

---

{{< figure src="tobias-shower.gif" alt="Nevernude shower" caption="\"There are dozens of us! That actually want to shower onboard like a person.\"" >}}

When someone says they live aboard a sailboat, most land-dwelling folk have a single mental model of what that means. But really, "I live on a boat" is as vague as "I live in a house." Do you have a sprawling estate with a guest house and an indoor pool, or a dilapidated one bedroom ranch with a sinking foundation and a leaky roof? The truth is that liveaboard experience varies even more than living on land \- regulations and codes create rigid minimum standards to occupy a land dwelling, but on the water no such rules apply. Living aboard can be little more polished than "sea camping," or it can be as luxurious as a five star hotel; while things like electricity, internet, and air conditioning all influence where on the quality-of-life spectrum your vessel will fall, two elements far outweigh all others in importance: how you poop, and how you clean up. The Jimmy Shower is how I solved the latter in a way that is *adjacent* to the usual options and, I think, gives *Defiant* the very best combination of comfort, cost, water and power efficiency, and normalcy. 

I am not a sea camper. While sponge baths in sea water or naked deck showers with a hand-pumped bladder probably would have seemed novel to me at 25, today I have a life with responsibilities. There are times when it is cold out (maybe snowing), and dark, and I need to clean up, put on a suit and get on an plane for a meeting; my boat is my only home, and in those moments I need a hot shower that leaves me feeling clean enough to put on a shirt with a tie. But I also have no desire to support the cost, complexity, and resource demands of a "floating condo" \- a showering experience indistinguishable from that a resort hotel, requiring at the very least an onboard water heater and either massive freshwater tankage or a watermaker (or both), or a short tether to a dock pedestal. 

## Why Not The Floating Condo Route?

*Defiant* has a full tub/shower in the head (really unheard of in a 36ft sailboat) and was set up to have a hot water tank, mixer, and handheld shower that was basically the same as being on land. The previous owners had removed the water heater and all the plumbing to use the shower and additional space for storage \- so why not just reverse the process and restore the original boatbuilder's intent?   
Here's the footprint: 

- Showering via continuous flow uses between 12 and 20 gallons (conservatively) per shower. *Defiant* has 75 gallons of tankage \- so every single shower could use **a quarter of my water supply**.   
- A water heater will draw around 1.2kWh of power every day \- much more if it is poorly insulated. *Defiant* stores a little over 11.5kWh onboard, so that is **10% of my total power storage per day of use**. Yes you can supplement that by running the motor to help heat the water (if you have it plumbed), and you might play with turning the water heater off (though the spin-up heat cost is usually higher than just keeping it running). *Defiant* has a little over 1kW of maximum production between solar and wind, which in practice is about half that most days. **This means that producing at 100% my solar and wind still will not cover the daily consumption of just the water heater** (forget about the electronics, cooking, diesel heater, TV, internet et al). 

If *Defiant* is to be on the hook for one week at a time, with another week's buffer to account for weather and other surprises, there is no way this math can work. The traditional answer to this is "run the motor," and that's fine, but before I went straight to burning dinosaurs maybe there was room to rethink things a little.   
{{< figure src="image1.png" caption="I could not have asked for a better place to start. <i>Defiant's</i> single head is really amazing for a 36ft monohull." >}}

## The Requirements

I was working with a great structural foundation \- the tub and shower curtain go a long way to normalize the experience over a wet head. Now, I had 2 consumption metrics where I needed to move the needle: water and power. 

For power reduction, my first thought was the shower heads with heater elements built into them that I had seen all over Puerto Rico. These compact units plug into a 110v socket above the shower head, and as water flows through it is heated. I looked all over for one that had a low enough wattage draw \- even with the 3K inverter it was hard to find one that would fit into my power budget. Eventually I settled on a Brazilian-made unit of questionable quality to perform my test. But what about water volume?   
I got to thinking about [navy showers](https://en.wikipedia.org/wiki/Navy_shower) \- the most obvious solution for minimising water consumption. But I hate fumbling for a switch on the showerhead with soap in my eyes, and more importantly, I wanted "water off" to be *the default*, so guests are less inclined to burn through my entire water tank in a single sitting. A bit of searching turned up a foot-controlled valve used at hospital hand wash stations. Perfect\! 

This thing would be less like a conventional shower served by water-and-power guzzling home infrastructure, and more like targeted blasts of water to get you clean. As I was planning out the prototype, I would describe it to people "like the scene in Pulp Fiction in Jimmy's back yard, with the hose" and so it became the "Jimmy Shower."  
{{< figure src="image2.jpg" caption="&ldquo;OK, gentlemen, you've both been to county before I'm sure. Here it comes.&rdquo;" >}}

Now it was time for a mock-up rig to conduct experiment:   
{{< figure src="image3.png" caption="What could possibly go wrong?" >}}
{{< figure src="image4.png" caption="Floor switch, left dangling for now." >}}
Unfortunately this experiment was largely unsuccessful. The power draw from the little unit spiked to more than double the rated 1300W, immediately tripping not only my panel main and pedestal breaker, but the entire dock went dark on my side of the marina 🤦. And *still* the water was ice cold. The bursts of water passing through the heat element did not give the unit time to reach temperature; even if I could get the unit's power draw under control, I was going to have to dump precious gallons of cold water down the sink every time I wanted a little warm burst, defeating the purpose. 

## The Electric Kettle

I have a 110v electric kettle that I use to make coffee a few dozen times a day. It will bring 4 cups of water from room temp to 100℃ in less than a minute, and does so with a nominal load on the inverter. I got to thinking, *this is all I need*. A small volume of water, heated to a boil slowly, then mixed with the fresh line to produce small, hot bursts of water in the shower. I started looking at how I could harvest the parts from a kettle when my brother suggested a much better element source \- a tiny tankless water heater designed for hand wash stations. While the rate of rise (how much heat the unit can add to water as it flows through) was not enough to bring room temperature water to shower temps in one pass, I could use a little tank and *recirculate it back through the unit* \- adding a few degrees to the water in each pass until it reached the desired temperature. 

My first design had the heater unit and tank mounted behind the shower bulkhead, running the hot water line around the tub, down to the switch on the floor, then up to the shower head. This presented a few issues: first, a remarkable amount of heat would be shed by all that piping. Second, the water would sit in that long pipe run and cool between blasts \- while I was lathering, the water would be getting colder, even though I was burning watts to keep it warm way back in the tank. Third, it looked like shit \- pex running all over the tub, *in* the tub, then back up to the showerhead, valves on the walls… there was no good way to hide all that plumbing. 

So I went back to the drawing board and re-designed my shower system as an all-in-one box.
{{< figure src="image5.jpg" caption="The first pass was a bit of a Frankenstein's monster." >}}
The parts are basically the heating element (harvested from an [eemax water heater](https://www.supplyhouse.com/Eemax-SPEX2412-SPEX2412-FlowCo-Electric-Tankless-Water-Heater)), a small DC-powered pump, an aluminum coolant reservoir tank, a DC temp gauge, a SPDT relay, a one-way check valve, an electric valve, a couple of transformers, a big green power switch, and an air button used for garbage disposals. It works like this: 

1. When it is time to shower, turn on the box (via the big green power switch). This energizes the temp gauge, transformers and relays. With the button un-pressed, power goes to the heating element and the DC pump.   
2. The pump circulates water from the reservoir tank into the heating element, which heats the water and pushes it back into the tank, which the pump circulates back into the heating element… you get the idea.  
3. As the water temp rises in the tank, you see the temp go up on the display. Once the water gets to around 90℉, it is time to get in the shower (I find that anything warmer than 80℉ is fine for showering, but 100℉ is really nice).   
4. When you step on the air button, the relay is flipped and the electric valve is opened, blasting you with water directly from the reservoir tank (only a few inches of travel so no heat is really lost here). At the same time the pump is cut off, but the heating element continues to heat water as it now flows into the system from the fresh water supply.   
5. You only need/want a 1-3 second bursts, in which case the reservoir tank will drop roughly 10℉ and begin to climb back up (I find it's about 1℉ per second). Then it is ready for you to blast again.   
6. If you were to hold the button down continually for 10-15 seconds for some reason, the water will eventually reach room temperature as the heating element just isn't that powerful. However, you quickly become aware after using this setup for a few days, that 15 seconds is a *long* time to be flooded with water at full house pressure. Too long really.   
7. If you are busy lathering for a while, the unit may reach the max temp of 130℉. At this point the heating element cuts off, but the pump continues to circulate. This is really, really hot water \- some people love it, I'm not a fan. So I'll typically do short bursts to cut in supply water and cool this down if I can (or just not let it get this hot). 

Along the way I ran into a few challenges: 

- **Most garbage disposal buttons are latching switches**. This means "step once for on, again for off" which is exactly what I didn't want. I did find a supplier, but they only sold batches of 1000 switches \- a few more than I wanted. Eventually I found the exact part number and did find a one-off seller on eBay (for almost as much as the batch of 1000\) and was good to go.   
  {{< figure src="image6.png" caption="Finally found one that was non-latching!" >}}
- **The initial hose I purchased was garbage.** This was an Amazon buy rated double my house pressure and 300℉. My first test run proved different results:   
  {{< figure src="image7.png" caption="This is fine." >}}
  I replaced all the lines with reinforced PVC tubing (and was now able to use a reasonable number of clamps as well)  
- **My first temp gauge was bad,** which was just dumb luck. I was ecstatic the first time the box ran and the little number gauge clicked up\! 70℉, 75℉, 85℉… it was working\! But then it got to 135℉ and kept going, until I finally stepped in at 165℉ and turned the box off. Hot showers are great, but scalding the flesh off a person not so much. I noticed that the temp cutoff relay wasn't clicking, so my first thought was to replace the relay. No luck. Then I tried moving the relay to higher in the tank, still no good. Then I piggybacked off the relay in the heating element, and *still* the high temp cutoff would not fire\! At this point it finally dawned on me to use a heat gun where I learned that the temp gauge was accurate right to about 120℉, and then went bonkers. The tank and heating element were right at 129℉, but the gauge just kept climbing into space. Even after the heating element cutoff *did* kick in, the temp gauge just kept going. I ordered another temp gauge, swapped it in, and everything just worked.   
  {{< figure src="image8.png" caption="The culprit: a faulty $10 temperature gauge." >}}
  {{< figure src="image9.png" caption="Testing with the heat gun. It works!" >}}

## Installation

Now that the unit proved to work in practice, it was time to polish her up a bit. I went with teak ply and edge banding because what other wood are you going to use in the shower of a shippy old boat? I also elected for bronze screws everywhere, to try and keep things with the time period. For the showerhead I was forced to use "oiled bronze" which I kinda hate; I will leave it to future me to replace the head with an antique bronze head if I can find one.   
{{< figure src="image10.png" caption="The finished box cuts, ready for the banding." >}}
{{< figure src="image11.png" caption="Banded and test-fitted, so far so good!" >}}
The whole box sits on the inner bulkhead of the shower, with water supply and power both coming up from behind the v-birth door and through the back of the unit. That means no exposed pipes, wires, and no mechanical clutter in my shower. There is still the air hose line that runs down to the foot switch, which I will eventually mount to the corner bead in copper pipe to give it a more polished look. Now I just need to clean up the holes left by the original hardware, re-caulk, and *Defiant* will have a proper shower.  
{{< figure src="image12.png" caption="No mess, no wires or pipes, just a little cosmetics and we're in business." >}}
{{< figure src="image13.jpg" caption="The finished product, teak-oiled and in service!" >}}
{{< figure src="image14.jpg" caption="I have an oiled bronze cap for the plastic fitting, but I am holding out for something a little more antique." >}}

## The Results

I am really happy with the showering experience on *Defiant*. I flip the switch, wait for less time than it takes most airbnb showers to heat up, and then have what has come to feel like a totally normal, hot, and super revitalizing shower. I am genuinely clean all over, every morning. I never noticed before how much time in the shower we are not actually under the water stream; any time you need to lather up or let your conditioner work, standing in the water would be "rinsing off" \- so we stand next to, or barely in, the flow of water. So it's not surprising that just a little bit of awareness \- namely, stepping on a button when I *actually want water* \- can give me basically the same experience for a whole lot less resources. What kind of resources are we talking about? 

- **Most daily showers consume around 1 gallon of water.** Washing my hair can consume a bit more as Kevin Murphy stuff takes forever to rinse out, but hair days are still only about 3 gallons. That's a 20:1 ratio compared to a traditional land shower.  
- **Taking a shower uses less power than making coffee**. This morning I fired up the electric kettle to brew much needed caffeine, then took a quick shower. The coffee kettle used 67Wh, the shower 60Wh. Another 20:1 ratio for power\!   
- **I shower as often as I want**. This is the most important quality of life impact of the new shower. On my first boat, showering meant either using the marina bathhouse (nothing like rowing a dinghy in from an Annapolis mooring ball wearing a bathrobe and flip-flops on a frosty morning) or a sponge bath in the wet head that never left any sense of "clean". It was not just a hassle, it was demoralizing; when you find yourself debating if it's worth the hassle of showering today, you can't help but feel you have made a terrible wrong turn in life. Now, a hot shower is a low-cost constant. Anywhere *Defiant* goes, I know I have that extra bit of comfort with her. 

And yes, even on those very cold winter mornings, the Jimmy Shower makes enough ambient heat in a few seconds of water flow to steam up the bathroom mirror 😃.  
{{< figure src="image15.png" caption="When you really need one, few things can top a hot shower." >}}
