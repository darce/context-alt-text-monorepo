# Debugging: The 9 Indispensable Rules — distilled

> **Source**: David J. Agans, *Debugging: The 9 Indispensable Rules for Finding Even the Most Elusive Software and Hardware Problems*, AMACOM 2002 · extracted from `../debugging-9-rules.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory that gives diagnosis a *procedure* rather than epistemics or prevention. Its nine rules are ordered discipline for the interval between "bug report exists" and "fix verified" — and every rule has a characteristic, observable violation (proposing a fix without a repro, closing an issue as "can't reproduce anymore", bundling speculative changes). That violation-cue structure is directly fireable by a reviewing agent: the rules were literally written as a wall poster to catch engineers mid-mistake. Explicitly out of scope for the book (and this file): bug prevention, QA/test coverage, and triage/prioritization — it starts after someone decides a bug must be fixed.

## Chapter map
- ch-1 — Introduction: scope — finding causes fast; debugging (broken design) vs troubleshooting (broken instance); what the rules don't cover
- ch-2 — The Rules: the nine-rule list + the violation→correction spine table
- ch-3 — Understand the System: read the manual/spec cover to cover; know the road map, the tools, and look details up
- ch-4 — Make It Fail: reproduce before anything else; stimulate vs simulate; taming intermittents; "but that can't happen"
- ch-5 — Quit Thinking and Look: see the actual failure mechanism before fixing; instrumentation; Heisenberg; guess only to focus
- ch-6 — Divide and Conquer: successive approximation over the failure path; upstream/downstream; start at the bad end; fix known bugs first
- ch-7 — Change One Thing at a Time: rifle not shotgun; back out non-fixes; compare good vs bad runs; what changed since it worked
- ch-8 — Keep an Audit Trail: write down what you did, in order, with results; correlate to timestamps; version control as audit trail
- ch-9 — Check the Plug: question foundation assumptions; startup conditions; test the tool itself
- ch-10 — Get a Fresh View: ask for insight/expertise/experience; report symptoms not theories
- ch-11 — If You Didn't Fix It, It Ain't Fixed: prove the fix; cycle fixed→broken→fixed; fix cause and process
- ch-12 — All the Rules in One Story: Engineer A (guessed noise, shipped non-fix) vs Engineer B (looked, fixed in 90 min)
- ch-13 — Easy Exercises: four annotated war stories mapping actions to rules (only novel rules extracted here)
- ch-14 — The View from the Help Desk: applying the rules remotely through an unreliable proxy — the agent-relevant chapter
- ch-15 — The Bottom Line: the rules are universal, fundamental, essential; post-incident review question

## ch-1 — Introduction {#ch-1}

- Scope: **finding the cause of a known failure and fixing it**. Not prevention (process/reviews), not detection (QA/test coverage), not triage (severity/priority). The rules fire after "this must be fixed" has been decided.
- **Debugging vs troubleshooting**: debugging = design doesn't work as planned (new, unknown problem); troubleshooting = a known-good design has a broken instance (deleted file, bad part, misconfiguration). The rules apply to both; symptom→fix lookup tables (troubleshooting guides, runbooks, known-issues databases) apply only to troubleshooting — consult them for known systems (that's ch-10, Get a Fresh View), but they cannot help with novel failures.
- Core claim from 26 years of field data: when a bug took long to find, it was because a fundamental rule was neglected; once applied, the problem fell quickly. The rules are obvious but not easy — they are "neglected in the heat of battle", which is exactly why a checklist/reviewer needs to enforce them.
- Debugging "as an art" is the anti-position: the easy way and the artistic way do not find problems quickly.

## ch-2 — The Rules {#ch-2}

The nine rules, in order, each with the observable violation a (coding) agent commits, the corrective action, and the book's compressed war story:

| # | Rule | Observable agent violation | Corrective action | War story (compressed) |
|---|------|---------------------------|-------------------|------------------------|
| 1 | **Understand the System** | Editing/diagnosing code whose contract it never read: guesses an API default, a config semantic, a pin/parameter order from memory; skips the referenced doc/spec | Read the manual/spec/schema for the failing component cover to cover before theorizing; look up (don't recall) every default, signature, and parameter | Interrupt controller never fired: page 37 of the data book said interrupts need a deselected clock strobe his cost-saving design never produced. All-nighter ended when he finally read the book (ch-3) |
| 2 | **Make It Fail** | Proposes a fix without having reproduced the failure; no failing command/test cited before the diff | Reproduce deliberately and repeatably from a known starting state; write the repro steps down; only then debug | Dealer inspected a car at 11 a.m., 37°F, for a whine that only occurs below 25°F in the first 10 minutes — found nothing, fixed nothing (ch-4) |
| 3 | **Quit Thinking and Look** | Asserts a root cause with no observation behind it (no log line, trace, breakpoint, or failing assertion cited); starts "fixing" the hypothesized mechanism | Instrument the system and watch the actual failure mechanism happen before touching the code | Junior engineers spent months building a memory-timing fix board for a "marginal timing" theory; senior engineer injected `00 55 AA FF`, saw `00 55 55 AA FF` — a doubled write pulse from bus noise, nothing to do with memory timing (ch-5) |
| 4 | **Divide and Conquer** | Reads the whole system linearly or verifies working components first; no bisection of the failure path (or of history) | Successive approximation: pick a midpoint on the bad path, determine which side the bug is on, halve again; start from the failure and work upstream | Hotel-reservation tech chased bad serial signals by halving the wiring path — computer end, breakout box, cable — to cracked solder joints, then a miswired purple wire (ch-6) |
| 5 | **Change One Thing at a Time** | Diff bundles several speculative changes "to see if it helps"; an experiment that didn't help is left in while the next one starts | One variable per experiment; if a change doesn't fix it, back it out immediately | Engineer added framing bits on a guess; it didn't help but he left it in. The real fix then still sounded bad — his leftover change was corrupting audio on its own. Hours lost re-verifying a correct fix (ch-7) |
| 6 | **Keep an Audit Trail** | Debugging across many attempts with no written record of what was tried, in what order, with what result; relies on conversation memory | Log every action and result with timestamps as you go; save and annotate the failing logs | Video chip dropped 30 fps→2 fps "randomly" for days; the audit clue was what shirt he wore — moving plaid flannel overloaded the compressor. The insignificant-seeming detail was the key (ch-8) |
| 7 | **Check the Plug** | Deep-dives component internals before checking foundations: wrong binary/branch running, service not started, env var unset, stale build, tool misconfigured | Question the "obvious" assumptions first — is it plugged in, initialized, the version you think? Test the test tool itself | Cold showers blamed on the water heater for months; the upstream furnace thermostat was set to 165° instead of 190°. He'd bounded his search below the real problem (ch-9) |
| 8 | **Get a Fresh View** | Grinds solo in a rut past the point of progress; when it does ask, it hands over its theory instead of the symptoms | Ask (colleague, expert, vendor, docs, bug database) early; report symptoms, conditions, and what's intermittent — never your theory | Brake-light fuse blew in reverse; a colleague said instantly "dome light wire pinched against the frame — happens all the time." Minutes instead of days (ch-10) |
| 9 | **If You Didn't Fix It, It Ain't Fixed** | Declares fixed without re-running the original failing sequence; tests the fix under different conditions; accepts "can't reproduce anymore" as closure | Re-run the exact repro against the fix; then remove the fix and confirm it fails again, restore and confirm it passes (fixed→broken→fixed) | Shop charged $75 for "an electrical problem", never reproduced the stall, car stalled next day; a 50-cent fuel filter — found via repro reasoning — was the fix (ch-11) |

## ch-3 — Understand the System {#ch-3}

- You need a working knowledge of what the system is *supposed* to do, how it's designed, and why — before you can know why it doesn't.
  - Understanding the system ≠ understanding the problem ("First, get a million dollars…"); it's the precondition for locating the problem, and later for fixing it without breaking something else.
  - If you don't understand some part of the system, that is reliably where the bug is — you were more likely to mess up what you didn't understand at design time. Not just Murphy.
- **Read the manual, first** — not "when all else fails".
  - For your own product: functional spec, design docs, schematics/architecture, the code and its comments.
  - Two war stories where the answer was literally in a comment: `/* Caution—this subroutine clobbers the B register */` (the clobbered B register was the bug); a text search for "bug" found `/* DJA—Bug here? Maybe should call these in reverse order? */` — reversing the order fixed it.
  - Don't *trust* the docs — manuals and engineers can be wrong, and many hard bugs live in that gap — but you still need to know what they *thought* they built.
- **Read everything, cover to cover**: the section you skipped holds the clue.
  - The function you assume you understand is the one that bites you; the ignored corner of the schematic is where the noise comes from; the obscure timing parameter is the one that matters.
  - Canonical: two "identical-spec" memory chips differed only in a between-access wait spec nobody read; the design met neither chip's spec, and the four-circuit boards crashed at high temperature while "identical" three-circuit boards happened to keep working.
  - Application notes and vendor errata are prior-failure catalogs — read this week's common mistakes from the vendor's site before debugging their part.
- **Reference designs / sample code**: written by people who know their product but skip real-world practice (error recovery is the most-skipped shortcut). Lifting one without understanding it imports its latent bugs and its unstated envelope — the ch-3 opening bug was a frat brother's copied design that had never needed interrupts.
- **Know what's reasonable**: baseline knowledge of normal (endianness, caching, tri-state buses, what a chainsaw sounds like) is what lets anomalies register as anomalies.
  - Without domain fundamentals you can't debug the domain at all — hand it to someone who has them (ch-10) rather than flailing.
- **Know the road map**: know what every block and interface is supposed to carry, so you can pick bisection points (ch-6).
  - Black boxes are fine if you know their interface contract — probing the interface still localizes the bug to inside vs outside the box.
  - Car example: engine and tires speed up together at highway speed; downshifting decouples them, so a tap-tap that tracks the tires, not the engine, is a rock in the tread.
- **Know your tools** — capabilities and blind spots:
  - Source-stepper: shows logic errors, not timing/races. Profiler: timing, not logic. Logic analyzer: lots of data, can't see noise. Analog scope: sees noise, stores little.
  - The "set a breakpoint just before the crash" suggestion is a category error — if you knew where that was, you'd be done. The workable version: record a rolling trace and trigger the capture on the watchdog/crash signal, then read backwards.
  - Know the build tools too: what the compiler/linker/allocator does to your source (alignment, allocation, reference handling) causes bugs invisible in the source (see ch-13 touchpad story).
- **Look it up — don't guess**: pinouts, function signatures, parameter order, defaults. Detailed facts are written down somewhere; memory-based "knowledge" produces falsely reassuring observations (probing the wrong signal that happens to look right, skipping past the swapped parameters just as the author did).
  - Kneejerk lore ("don't use the 1489A, it runs hot") propagated a broken circuit for years because nobody checked the pinout; the junior who looked it up found the team had wired input to a bias pin — no noise immunity, excess heat, wrong part choice, all from one unchecked "fact".
  - Einstein didn't memorize his phone number: "It's in the phone book."

## ch-4 — Make It Fail {#ch-4}

Three reasons to reproduce before anything else: (1) so you can **look at it** (ch-5 is impossible without it); (2) so you can **focus on the cause** — knowing the exact failing conditions narrows suspects; (3) so you can **tell when it's fixed** — a 100%-repro sequence makes fix verification binary (ch-11 is impossible without it).

- **Do it again**: one failure is not enough — adopt the three-year-old's "Do it again!" attitude.
  - Write down each step as you reproduce; then follow your own written procedure and confirm it really causes the error.
  - Exception: destructive/painful failures — change as little of the system and sequence as possible to make repetition safe.
- **Start at the beginning**: bugs depend on machine state; start the sequence from a known state (fresh reboot / clean checkout / empty DB).
  - Report the setup state, not just the trigger — "the car goes through the car wash every morning" matters to the mechanic hunting frozen windows.
- **Stimulate the failure** (good): make the conditions occur on demand.
  - Automate the repro (the pong game's robot paddle: wiring the paddle to the ball's position freed his eyes for the scope); run it all night ("software is happy to work all night, and you don't even have to buy it pizza").
  - Amplify conditions — hose on the leaky window instead of waiting for a southeast storm; load generator for the traffic-dependent bug.
  - Make changes at a level that changes *how often* it fails, never *how* it fails. And don't over-amplify into a new failure (fire hose → shattered window; heat gun → melted chip).
- **Don't simulate the failure** (bad): don't rebuild a guessed mechanism on a different system/config and study that.
  - Either your guess is wrong or the copy's conditions differ: the simulation works flawlessly, or fails a *new* way that hijacks the investigation (the disk-write test that "proved" Windows was too slow while the word processor kept dropping paragraphs).
  - Red flag phrase: substituting a "seemingly identical" environment and expecting the same failure. It isn't identical — the leaky window's gap was in *that* window's caulking.
  - If it only fails at the customer/production site: bring the failing equipment in, or send the engineer (and instrumentation) to it — don't approximate it in the lab. "How many engineers to fix a lightbulb? None: 'can't reproduce it — the bulb in my office works fine.'"
  - Limited legitimate use: reproducing on a second system proves it's a design bug (not one broken unit) and which configs are implicated — but never keep modifying the simulation until it fails; debug the system that fails, in the configuration that fails.
- **Intermittent ≠ random**: you know exactly what you did, not all the *conditions*.
  - Enumerate uncontrolled factors — software: uninitialized data, random inputs, timing variation, multithread synchronization, outside devices/traffic; hardware: noise, vibration, temperature, timing, parts/vendor variation.
  - Control each candidate; if controlling one makes the bug vanish, you've found the governing condition — now sweep its values until failure is deterministic.
  - If you can't control it, randomize/intensify it (inject noise, vibrate) to raise failure frequency — while watching that you haven't created a different error.
  - Mainframe crashed mid-afternoon at varying code locations: the 3 p.m. coffee break — all vending machines at once browned out the power supply.
- **When it stays intermittent, capture instead of chasing**: log everything on *every* run so any failing run is fully described after the fact; work from captured failures as if they reproduced on demand.
  - Videoconferencing bug (1-in-5 calls dropped to audio): logs showed a "surprise command" present in every bad call, absent in every good one — a stale command buffer from the previous call, flushed or not by luck.
- **Lies, damn lies, statistics**: with rare failures your sample sizes can't support "it fails more when I click with the left hand" folk patterns; chasing coincidental differences wastes days ("you'd do better betting the slots in Vegas").
  - Trust only conditions *always* or *never* associated with the failure in captured logs; those are the discriminators worth pursuing.
- **Did you fix it, or did you get lucky?**: statistical fix-testing ("failed 1/10, now 0/28 — ship it") is self-deception.
  - Find the deterministic signature: the condition that, when present, yields 100% failure — even if the condition itself appears intermittently.
  - Bonding story: garbled data occurred exactly when the phone company connected the six lines out of order; the fix was proven when out-of-order sequences occurred *and calls still worked* — independent of how often local teenagers' phone traffic happened to jumble the lines.
- **"But that can't happen"**: when a report seems impossible, what can't happen is your assumed mechanism ("that"), not the reported failure.
  - Accept the data; make it fail in the skeptic's presence; then hunt for the real, entirely possible mechanism.
  - Car Talk puzzler: car fails to start only after buying three-bean tofu mint chipped-beef ice cream — the unpopular flavor was hand-packed, and the wait was long enough for vapor lock. The flavor was a proxy for elapsed time; "the flavor can't matter" was true and useless.
- **Never throw away a debugging tool**: engineer the repro/instrumentation tool properly — document it, check it into source control, build it into shipping systems so it's available in the field.
  - The robot paddle built to reproduce a pong bug later became the product's store-display demo feature and helped sell the game.

## ch-5 — Quit Thinking and Look {#ch-5}

- Thesis: engineers guess because thinking is easier than looking, but "there are more ways for something to be broken than even the most imaginative engineer can imagine."
  - Fixing a guessed mechanism usually fixes something that isn't broken — costing time, possibly masking the bug (timing shift hides it and you "go home happy"), possibly breaking something else.
  - When your guesses are all disproved you still have the original work left, minus the time spent. The colleague who always announced "I bet it's a such-and-such problem" would have lost that bet almost every time — smart, understood the system, never looked, never had enough information.
  - Opening story: junior engineers ran a loopback test, declared the host path good, theorized "marginal memory timing", and spent *months* hand-building a timing-fix daughterboard. It changed nothing. The senior engineer hooked up the analyzer, injected `00 55 AA FF`, saw `00 55 55 AA FF` — the right data written *twice*: a noise glitch was splitting the write pulse, sending every subsequent byte one address off. The loopback test had been blind to it because writing a register twice reads back fine.
- **See the failure, not the symptom's shadow**: what you noticed is the *result* of the failure (light didn't come on); the failure is upstream (broken switch? broken filament? wrong switch flipped?). Look until you have seen the actual mechanism misbehave.
  - Well-pump story: wife heard "a motor run ten seconds, occasionally"; the pump-salesman neighbor replaced the well pump. No pressure loss, no puddles, nobody had stood near the pump when it ran. It was the air compressor left on in the garage, re-pressurizing a leaking hose. Fixing without seeing = stirred-up sediment, chlorine, and the noise continuing.
  - Server "crashed and restarted" nightly ~11 p.m.; weeks of process monitoring found nothing. Staying late and *watching* found the janitor unplugging it for the vacuum cleaner.
- **See the details — how deep?**: keep looking until the visible failure implicates a small enough piece of the design to examine directly.
  - Video-compression story: guessed "motion estimation is weak" but didn't read the code — instead overlaid detected motion vectors on the output screen (color=direction, brightness=magnitude) → vertical motion detected, horizontal mostly missed → dumped the search calculations → the search algorithm skipped most horizontal positions. The match logic (the "complicated" suspect) was fine; stopping one level earlier would have sent them auditing the wrong code for months.
  - The book's yardstick: *the measure of a good debugger is not how good the guesses are, but how few bad guesses get acted on.*
  - Bonus for intermittents: once you can see the mechanism-level failure, fix-verification stops being statistical — you can see the glitch is gone (ch-11).
- **Instrument the system** — design it in:
  - Hardware: test points, test connectors, readable-as-well-as-writable registers, status LEDs, the built-in CPU temperature sensor.
  - Software: debug build + source debugger is only level one; production needs a debug window / status messages / **debug log file** since you ship release builds.
  - Structured messages: fixed columns; an accurate timestamp column; module/source; severity ("info", "error", "really nasty error"); expected-vs-actual values — consistent formats and keywords make logs filterable later.
  - Message switching at compile time (saves code, kills field debugging), startup time (easy, can't engage mid-run), or run time (hardest, best — customers can enable it remotely). Too much output changes timing and drowns the CPU — make it selectable.
  - Make instrumentation a product requirement and part of every functional spec/API definition; you're building the bugs in at design time, so build the debugging tools in too. Side effect: thinking about observability improves the design.
- **Build instrumentation in later** (when the bug arrives anyway): add it to the *same build/revision that failed* (else you're simulating, ch-4); re-run the repro afterward to prove the instrumentation didn't perturb the bug; `#ifdef` it out when done rather than deleting it.
- **Don't be afraid to dive in**: the advice "you can't modify production software, so swap modules at API boundaries to isolate the failing module" is condemned — it simulates the failure, presupposes convenient architecture, and dead-ends at module granularity with no way to look deeper. If there's a bug you'll have to rebuild to fix it, so rebuild to *see* it: debug build, add the statements, ship clean afterward.
- **Add instrumentation on** when you can't build it in: scopes, analyzers, meters — but the tool must be fast/accurate enough for what you're measuring (a low-frequency scope can't show high-frequency problems; your finger says "hot" but not "out of spec"). A VCR's frame-step once proved a display showed the same frame twice rather than frames out of order.
- **The Heisenberg uncertainty principle**: all instrumentation perturbs the system under test — debug builds change timing and code size, probes add capacitance, extender cards change bus timing, even opening the case changes temperature.
  - Unavoidable; so prefer less-intrusive methods, keep the effect in mind, and after adding instrumentation *make it fail again* to prove Heisenberg isn't biting you.
- **Guess only to focus the search**: guessing is legitimate for choosing *where to look first*, never as grounds for a fix.
  - Confirm the guess by seeing the failure; if instrumentation disproves it, back up and re-guess or bisect (ch-6). The motion-estimation guess was confirmed by looking; the match-logic guess was disproved by looking — both cheap because neither was acted on.
  - Sole sanctioned guess-fix: cause both highly likely *and* trivially cheap (swap the bulb — but you still shake the old one to hear the broken filament).
  - Counter-story: the in-sink hot-water heater — help line guessed "internal fuse"; friend bought and installed the awkward six-inch fuse in cramped quarters. Actual cause: tripped breaker, a few seconds to reset. Likely-but-*hard* fixes don't qualify for the exception.

## ch-6 — Divide and Conquer {#ch-6}

- The only rule that actually *finds* the bug; the other eight exist to make this one work.
- Method: **successive approximation** — know the search range, probe the midpoint, determine which side of the probe the bug is on, halve again. 1-in-100 found in seven probes; the same shape as binary search, ADC conversion, and the phone-company "yanker and feeler" wire-tracing procedure.
- Two preconditions:
  - **The range must contain the bug.** Assuming "the whole system" as the range is fine — halving is cheap. When the search converges on the *edge* of your range without finding the bug, your bounding assumption was wrong; widen the range (this is where ch-9 bites: the cold-shower bug was upstream of the assumed range; if your friend picked 135 in the 1–100 game, no amount of guessing inside 1–100 succeeds).
  - **Each probe must tell you which side you're on** — you need a good/bad discriminator at every test point (the hotel tech's was: which direction are the bad signals flowing?).
- **Upstream/downstream orientation**: data flows and gets corrupted when it passes the bug — clean water upstream, "smelly pink goo" downstream of the factory pipe you're hunting.
  - Signal/data correct at this point → bug is downstream; corrupt → upstream.
  - Crashes: breakpoint/print reached → crash is downstream (later in code flow); not reached → upstream.
  - Long calculations: stop midway, check intermediate results; wrong → move earlier, right → move later.
- **Inject easy-to-spot patterns** when real data is too random for corruption to show ("eliminate the mud; use clean water"):
  - `00 55 AA FF` exposed the doubled write; smooth color ramps make video mapping errors show as edges; a synchronized click+flash finds lip-sync loss; a wheel turning exactly 1 rev/4 s against frame-time markings exposes repeated/out-of-order frames; the 6800's `DD` "Drop Dead" instruction turned all address lines into clean square waves for scoping.
  - Caution: if the bug is pattern-dependent, an artificial pattern may hide it — Make It Fail again before proceeding (ch-4).
- **Start with the bad end**: never verify from the known-good end toward the failure — there are too many correct things to confirm (and, you hope, they're mostly correct).
  - Start at the observed failure and walk upstream; treat branch/tributary points as test points, probing a little way up each branch and following the bad one.
  - Furnace example: don't trace fuel from tank to spray head; start at the dead furnace, find fuel fine but electricity absent, walk up to the control box, meter each tributary (mains OK, thermostat OK, fire-safety fuse tripped).
- **Fix the bugs you know about, immediately**: multiple simultaneous bugs hide and distort each other; "that's broken, but it couldn't possibly affect this" is regularly wrong.
  - Fixing a known defect gives a clean look at the rest — the hotel tech could only see the slow terminal's one-directional errors after resoldering the breakout box's cracked joints. Sometimes two symptoms turn out to be one bug.
  - If a fix can affect anything else, land it before continuing to test — if it breaks something, you find out with maximum remaining time.
- **Fix the noise first**: defect classes that destabilize everything else get fixed before further diagnosis — hardware: glitches/ringing on clocks, noise on analog signals, jittery timing, bad supply levels; software: bad multithread synchronization, accidentally reentrant routines, uninitialized variables.
  - Counter-caution: weigh fix difficulty against likelihood it's really involved — the junior engineers' months-long timing board was "fix the noise" run on a *suspicion*. And don't become a perfectionist mid-hunt: GOTOs you find nasty but that cause no problems stay. ↔ contra the refactoring sources in this directory (opportunistic cleanup): *during a debugging session*, Agans says leave working ugliness alone; clean up after the bug is dead.

## ch-7 — Change One Thing at a Time {#ch-7}

- **Rifle, not shotgun**: swap/patch one candidate at a time.
  - Technicians who swap three or four components and find "hey, it works now" don't know which part was bad — and the hacking often breaks things that were fine.
  - Needing a shotgun means you can't see the target; the cure is better light and new glasses (back to ch-5), not more pellets.
  - Scientific-method framing: vary one factor while pinning all others (twin studies; the grade-school plant experiment — vary sunlight only, or you'll never learn pot color is irrelevant).
- **If a change didn't fix it, back it out now.**
  - Canonical audio war story: a speculative "add framing" change had no visible effect, so it was left in. When the real bug (a buffer-pointer error) was found and fixed, the system *still* failed — his leftover change was corrupting audio on its own, and audio clobbered twice sounds no worse than audio clobbered once. Hours were burned re-verifying a correct fix.
  - A change with no visible effect on the bug probably did something you didn't expect. (Car analogy: shifting to Neutral didn't start it, and the "finicky key" trick then failed *because* you never shifted back to Park.)
- **VGA-capture story** (pinning makes impossible observations trustworthy): all measurements bypassed and defaulted, only the pixel-phase parameter swept through its 8 positions — output jumped right then left, which "made no sense, but since nothing else was changing, I knew it was really happening." Vendor investigated: the phase parameter was misdocumented (0–359 actually mapped 0–89, then −270 to −1). He'd never have believed the parameter was faulty without single-variable isolation.
- **Grab the brass bar with both hands** (nuclear-sub control rooms): when alarms fire, engineers are trained to grip the brass bar until they've read *all* the dials and understand the system state — a positive action that beats "don't touch that dial", preventing reflexive fixes that confuse auto-recovery and bury the original fault under new conditions.
  - Fraternity Christmas party: right speaker died (melted wire short had blown the right-channel fuse); the brothers "tested" by swapping speaker wires at the amplifier — and blew the left fuse too. No music. Grab the bar.
  - For agents: when a run fails, read the complete failure output before editing anything.
- **Change one *test* at a time** too: varying the test sequence/parameters to improve reproduction is fine, but one parameter per iteration — and back out test changes that had no effect.
- **Compare with a good one — be a differencing engine**: capture a failing run and a passing run under maximally identical conditions (same machine, same build, consecutive tries — "don't even wear a different shirt") and diff logs/traces.
  - Instrument broadly: data unrelated to the bug appears identically in both logs and skims out; the bug is in the difference ("1-700-VID-TEST" vs "1-700-BAD-JEST").
  - No full automation exists for "find the bad stuff" — what you're looking for is never the same as last time; software can only format/filter so the difference jumps out at a knowledgeable reader. Expect mind-numbing boredom; look at the *whole* log if the suspect areas come up clean.
- **What did you change since the last time it worked?**: when a working system breaks, bisect versions to the first failing one; verify the previous version passes and that one fails; then read the diff.
  - Requires version control ("You do, don't you? If you don't, get one. Now.") — see ch-8.
  - Usually the new design is faulty; sometimes it's an incompatibility with an older, fine section (turntable story: new higher-output cartridge into the old amplifier input — flip the input switch, thirty seconds, godlike prowess).
  - Trap: the change may only *expose* an old latent bug — new timing or data size walks you into a hole that was always there. Reverting the trigger can be the short-term fix, but the real work is plugging the hole. Roof story: kicking a mysterious drip-catching tub out of position "caused" a ceiling leak; moving the tub back was the workaround, reshingling the roof was the fix.

## ch-8 — Keep an Audit Trail {#ch-8}

- **Write down what you did, in what order, and what happened** — every attempt, every result, as you go. You're instrumenting the *test sequence* the same way ch-5 instruments the system: each step and its result must be visible later to know which step to focus on.
- Any detail may be the key, and you can't know which while recording:
  - Plaid-shirt story: prototype video chip dropped 30 fps → 2 fps "randomly" across days; the trigger was noticed only when standing up made it fail — more shirt in the camera's view, and that day's shirt was plaid flannel. The compressor gave up on the hardest-to-compress moving pattern. The useful bug report named the shirt, the standing, and the required restart — and included a photocopy of the fabric so the vendor could reproduce it. Compare the useless versions: "chip occasionally slows down"; "it's broken."
  - Floppy that "worked once then failed", replacement after replacement — the live play-by-play audit revealed the customer stored each disk stuck to a filing cabinet with a magnet.
  - Sunday headaches: a mental diet audit trail → no Saturday coffee → caffeine withdrawal. Allergists run the same method as a food diary; it only works if you record symptoms *and* intake, both with times.
- **The devil is in the details**: "It's broken" and unannotated logs are useless bug reports.
  - Annotate debug logs with the conditions and symptoms the log doesn't record itself; say *which* log is the failing one and what the tester actually saw.
  - Be specific and consistent about referents (system A vs system B; "no remote video" is ambiguous in four ways).
  - Record magnitude and duration: "half-second barely audible hum" is ignorable; "six-second ear-piercing shriek" isn't. Chemistry-lab standard: give the reader enough information to accurately re-experience the event (how hot is the candle? bunker or no bunker?).
  - Barefoot-engineer story: only one person could feel the power-supply shock — everyone else wore shoes. The "irrelevant" detail (footwear) was the entire discrepancy between observers.
- **Correlate to timestamps**: "made a loud noise for 4 s starting at 14:05:23" lets you line symptoms up against the audio commands logged at 14:05:23 and 14:05:27.
  - Multi-system traces: synchronize all clocks before capturing, or spend the night mentally subtracting 1 min 23 s from one log.
  - Human-schedule correlations solve real bugs: crashes at the 3 p.m. coffee break = vending-machine brownout; garbage characters only on Fred's shift = Fred's gut resting on the keyboard as he reached for the coffeepot; crashes on George's shift = George pushing the print head back to type past the input limit.
- **Version control is the design's audit trail**: it tells you exactly what changed between last-good and first-bad versions (feeds ch-7's bisection) and protects working code from concurrent clobbering.
  - Configuration control > source control: track the *build tools* too — unrecognized tool variations cause very strange effects (ch-9's compiler stories).
- **The shortest pencil is longer than the longest memory**: don't trust recall.
  - Trusted memory loses the details that seemed unimportant (the critical ones), loses ordering and correlation, and can't be handed to anyone else except verbally — if you're still around.
  - Write electronically: diffable, attachable to bug reports, distributable, filterable by tools later. "Don't remember 'Keep an Audit Trail.' Write down 'Keep an Audit Trail.'"

## ch-9 — Check the Plug {#ch-9}

- **Question your assumptions**, especially the foundation/"overhead" ones (power, clock, heat source, environment): because they're general prerequisites, they're invisible while you debug details.
  - Cold-shower story: months evaluating valves and the hot-water exchanger while the upstream oil furnace was set to 165° instead of 190° (the previous owner's *backup* setting) — you can't make 140° water fast from a 165° source. He had bounded the divide-and-conquer range *below* the actual bug; fixing the furnace fixed the "sluggish heat" bug and the shower simultaneously.
  - "When you run into a problem that seems completely otherworldly, stop and check that you're actually on the right planet."
- Classic software forms of "is it plugged in":
  - Are you running the code you think you're running? Old binary still on the path, not rebuilt, not redeployed, not restarted, an easier-to-find copy shadowing the new one. Signature phrase: "Hmm, the new code behaves exactly like the old code."
  - Right driver installed? Right OS? Feature enabled in registry/flag/config? Power and clock actually present at the failing component?
- **Don't start at square three**: verify startup conditions — initialization actually performed, reset done, registers programmed, primer bulb pressed, switch set to ON (noticed "after six or seven fruitless pulls").
  - Implicit initialization (memory you assume starts zeroed) is worse: startup conditions are *sometimes* correct — until the investor demo.
- **Test the tool**: assumptions about build and measurement tools fail the same way, and tool bugs masquerade as system bugs.
  - Consultant benchmarked file I/O for weeks, puzzled that reads were slower than writes, optimizing everything: the dev environment's unspecified file mode defaulted to *text*, so every read scanned for line endings. He assumed binary, never checked — "and he never worked for us again."
  - Custom chip dropped interrupts; register-level simulation was perfect. Looking at the *gate level* the chip compiler actually emitted revealed the timing bug — the tool's output, not the design source, held the defect.
  - Measurement-tool checks: dead-battery continuity checker reads every joint as broken — touch the probes together first; finger the scope probe and check 5 V before trusting the trace; conditional debug prints must print *something* either way, so silence is distinguishable from "print is broken"; a 75° child-temperature reading means re-measure with a different thermometer; the oil gauge read one-quarter full on an empty tank until the furnace guy banged it with his flashlight.
- Assumption bugs are disproportionately easy to fix once seen — which is why skipping the check is so costly in wasted-effort-per-minute (and embarrassment). Nietzsche, as quoted: "Convictions are more dangerous enemies of truth than lies."

## ch-10 — Get a Fresh View {#ch-10}

- Three distinct things to ask for (besides a lap to dump the problem into):
  - **Fresh insight**: a differently-biased viewpoint escapes your rut. Even *explaining* the problem — to a colleague or the company's mannequin room — forces the facts into order and often solves it unaided (rubber-duck debugging, 2002 edition).
  - **Expertise**: someone who Understands the System better; they know the road map, give search hints, and later help design a fix that won't break the rest. Beware vague buzzword-laden theories (charlatan) and thirty-hour research quotes (consultant).
  - **Experience**: someone who has literally seen this before — the colleague who said, without hesitating, "dome light wire pinched against the frame, happens all the time"; the retired maintenance man's invoice: "$10 for the whack with the hammer, $9,990 for knowing where to whack."
- Sources: inside associates; the vendor (they know their product's common misuses; and if you found *their* bug — the VGA phase function — they confirm it and hand you a workaround); application notes and the vendor's current common-mistakes page; user groups/forums; troubleshooting guides for known systems (the TV-game techs' homegrown table: ball faster up than down → replace capacitor A); books and docs.
  - "When all else fails, read the manual *again*" — the second pass, focused by the failure, reveals what the first didn't.
- **Don't be proud**: asking for help signals eagerness to get the bug fixed, not incompetence — take pride in getting rid of bugs, not in getting rid of them unaided.
  - Inverse also holds — don't assume the expert is a god: the B-tree author, shown his own inexplicable rebalancing code, stared a moment and said "Hm. That's a bug." Hours had been lost on "I must be missing something" instead of "the expert may have erred".
- **Report symptoms, not theories** — the operational core of the rule.
  - Your theories are why you're stuck; laying them on the helper drags them into your rut, and your bias about what matters filters out the detail they needed. "If the theories were any good, there'd be no need to bring in help."
  - Do report: what happened, what you saw, the conditions, what's intermittent and what isn't. The doctor wants the back-pain description, not your internet self-diagnosis.
  - If you're the *helper*: cut off incoming theories before they poison you.
- **You don't have to be sure**: unexplained observations that merely smell related (the shirt was plaid; the flavor was tofu-mint) are data — report them, flagged as unexplained, without inventing a causal story.

## ch-11 — If You Didn't Fix It, It Ain't Fixed {#ch-11}

- Opening story: car stalls under sustained full throttle (L.A. hill, West Virginia hill, highway speed), restarts after a wait. The shop said "electrical problem", replaced wires, charged $75; it stalled the next day — they never reproduced the failure and never tested the fix. Reasoning from the repro pattern (full throttle drains the carburetor faster than a restricted feed refills it) + a coffee-machine fresh view ("dirty fuel filter") = 50-cent fix. "Just because you pay people $50 an hour doesn't mean they know how to debug."
- **Check that it's really fixed**: re-run the exact Make-It-Fail repro against the fix. Don't reason "the problem and fix are obvious" — you can't be sure until you test it.
- **Check that it's really *your fix* that fixed it**: for design fixes, cycle **fixed → broken → fixed** — remove the fix, confirm the original failure returns; reinstate it, confirm it passes. Only that cycle, changing nothing but the fix, proves causation.
  - Why: during debugging you changed other things (test sequence, tooling, environment, incidental edits, random factors). If one of those masked the bug, your "fix" ships to customers who don't get the incidental change — and fails for all of them.
  - Sesame Street: Grover hops yelling "Wubba! Wubba!" while Betty Lou presses the ON button; the computer turns on, and Grover concludes he's found a valuable repair technique.
  - Exemption: repairing a broken *instance* rather than a design — no need to reinstall the dirty fuel filter, and don't re-implant the heart-transplant patient's old heart.
- **It never just goes away by itself**: "we can't seem to make it fail anymore" means the conditions changed, not the bug. It will return — typically at a customer.
  - Recovery path: go back to ch-4 — original system, original test scenario, un-randomize the conditions. If old software fails and new doesn't, diff and explain *why* before believing it's fixed.
  - If genuinely out of reproduction time, ship with a **field trap**: instrumentation that captures full context if it ever fires. "Thanks! We've been trying for months to capture that; please e-mail the log" beats "Wow. That's never happened here."
- **Fix the cause**: a failed part with an unaddressed reason for failing eats replacements.
  - Transformer story: dead stereo → "bad transformer" → months waiting for the replacement → an hour of music → smoke. The eight-track deck was shorted all along; the first transformer's death was a symptom. He never measured what the transformer was driving — thrown-out stereo, twice-bought part.
  - The Christmas-party fuse (ch-7) is the same failure: replacing the blown fuse (with the left channel's!) without fixing the melted-wire short.
- **Fix the process** when the causal chain continues past the artifact: oil on the floor → wipe it (symptom) → tighten the leaky fitting (cause) → bolt the machine down with 4 bolts, not 2 (deeper cause: vibration) → *fix the design process that keeps under-specifying vibration*, or the next machine ships with two bolts and the oil returns. Where the chain crosses from product into process, follow it.

## ch-12 — All the Rules in One Story {#ch-12}

Battery-backed memory intermittently unreadable at startup. **Engineer A** guessed "bus noise", added a ground wire and capacitor, wrote the change order, shipped it to manufacturing — boards failed exactly as before (violated Make It Fail, Quit Thinking and Look, and If You Didn't Fix It). **Engineer B**, 9:00 a.m.: scoped the data lines — failure data was *all 1s*, not noise-corrupted; looked for the read pulse — *absent*; read the controller's data book (its job: block access when power looks bad); 9:45 called the chip vendor's applications engineer, who diagnosed it in one sentence (a diode between supply and chip power latches the "bad power" state); added the wire, **removed the fix, saw it fail, restored it, saw it pass** — done 10:15. Every rule appears; the delta between A and B is the delta the lexicon should enforce.

## ch-13 — Easy Exercises {#ch-13}

Four annotated stories; rules already covered above except these additions:

- **Finger-pointing prevents looking** (V.35 restricted-call story): software blamed hardware, hardware blamed software — both by *thinking*; neither looked. The debugger who owned both domains wanted the bug to be in his own stuff ("the leak being in the other end of the boat doesn't keep my end from sinking"). Detection cue: a diagnosis whose main content is which team/module is "obviously" not at fault.
- **The test rig can validate a broken product** (same story): QA's in-house ISDN emulator "emulated restricted calls beautifully" except it didn't actually strip the eighth bit — so the ISDN path passed a test the real network would fail. A passing test on an unfaithful simulator is a Check-the-Plug violation on the *test* side.
- **Masked errors resist observation at the output** (touchpad story): averaging math hid an off-by-one in calibration data almost everywhere; only looking at the *raw intermediate data* (the arrays, upstream of the math) made the corruption obvious. When output-level observation stays cloudy, move the probe upstream of the transformation. Root cause was an assumption about the tool: the programmer indexed one named array 55 past the other, assuming the compiler laid them out adjacently; it aligned them with a gap.
- Deliberately amplifying noise (a finger on the suspect pins) made an intermittent memory error fail on demand — but the observed signal was *ringing*, not noise: he looked and reported what he saw rather than concluding what he'd assumed (missing terminator; fix verified by remove/restore, then applied to all equivalent lines because the cause was common to them).

## ch-14 — The View from the Help Desk {#ch-14}

Remote debugging through an unreliable human proxy — structurally the situation of an agent debugging via a user's reports, or an orchestrator debugging via a sub-agent's summaries.

- Constraints: you're remote (can't see; can't trust that requested actions were performed), the contact is less skilled and jumps ahead ("the rough cases think they know what they're doing, and break it badly before they call"), and it's usually troubleshooting under time pressure (field system, workaround now, bug report to engineering later) — so shortcut temptation is maximal exactly where the rules are hardest to apply.
- **Understand the System**: your product knowledge plus its support history is the only solid ground; the unknown is the *other stuff* attached to it.
  - Prefer configuration-reporting tools (and third-party system inspectors) over the user's opinion of what's installed; if your product lacks config reporting, escalate that as a product requirement.
  - Get a system diagram early; agree on unambiguous names for the parts ("system A"/"system B") — reports built on ambiguous referents ("my machine died after talking to the other machine") are undecodable. If cables are involved, get cable diagrams.
  - Giulio story: weeks tuning protocol parameters over fax and broken English failed because no question ever surfaced the *circuit board he'd spliced into the middle of the cable* (to halve a clock); its power-supply noise on the cable ground was the whole bug. Moral: budget understanding-effort wide-first; when the area you went deep on comes up innocent, re-aim rather than dig.
- **Make It Fail**: how it broke is usually unrecoverable ("clicked all over the place, then it went crazy"; "someone spilled coffee in it"), but the broken state itself usually reproduces on demand — debug forward from the solidly-broken present, not the unknowable history.
  - Get the failure description concrete before anything: which systems, windows, buttons, fields; reboot to a known state if needed. ("It crashed" — confirm they're not describing the car-racing game.)
- **Quit Thinking and Look**, remotely: users don't look where you point, can't describe what they see, and substitute assumed answers for observations ("Okay, now right click in the text box." "You want me to write 'click' in the text box?").
  - De-humanize the loop: remote-control/screen-sharing tools put you back in the driver's seat; **log files e-mailed to you** carry the instrumentation (never make the customer read the logs — scary error text and misspellings await).
  - Label which log is failing vs working and timestamp the symptoms, or you'll receive `giulio.log` and `giulio2.log`; attach logs to the ticket and eventual bug report.
- **Change One Thing at a Time**: users changed everything before calling and changed nothing back. If module-swapping is the only division available, keep the replaced part, and restore it after the test. Full reinstall = shipping a new system: destroys the evidence, looks desperate, and is doubly embarrassing when it doesn't work — but it does establish a known base state.
- **Keep an Audit Trail** with error correction: after each instruction, make the user *say what they did in their own words* — not answer yes/no (they'll say yes regardless, for the same reason they misunderstood the first time). Keep asking "and then what happened?" — users omit the thing you'd never think to ask (typewriter-through-the-floppy, magnet on the cabinet).
- **Check the Plug**: verify even the insulting basics (the blank screen during a neighborhood power cut); no one is too stupid to use your product and you must not let them hear you laugh.
- **If You Didn't Fix It...**: the user being satisfied ≠ the bug being fixed. Feed the resolution back into the troubleshooting database with recognizable symptom phrasing; if it was a workaround for a real bug, file and escalate the bug — don't settle for wiping up the oil.

## ch-15 — The Bottom Line {#ch-15}

- The rules are **universal** (any system), **fundamental** (they select the specific tools/techniques), **essential** (skip one and the hunt degrades to guessing).
- Post-incident practice: after each debugging episode ask — was I efficient? which rule did I neglect, and what did it cost? That retrospective question is itself a fireable review step.
- For leads/managers: don't pressure people to guess their way to a quick fix; the rules *are* the fast path. The rules' names double as team vocabulary ("Quit Thinking and Look" as a complete code-review comment).

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Fix proposed with no reproduced failure (no failing command/test/log cited) | Reproduce first; write the repro steps; make them fail reliably | Without a repro you can't observe the mechanism or verify the fix — you can only get lucky | ch-4 |
| Root-cause statement contains no observation (no log line, trace, assertion, or diff of good-vs-bad run) | Instrument and watch the failure happen before changing code | Guessed mechanisms usually "fix" something that isn't broken and may mask the real bug | ch-5 |
| Plan says "rebuild a similar setup and see if it fails" while the failing system/config is reachable | Stimulate the failure on the failing system; don't simulate it elsewhere | The copy differs in the one condition that matters; it works flawlessly or fails a distracting new way | ch-4 |
| Repro run starts from unknown/dirty state | Start the sequence from a known state (fresh boot/clean checkout/reset DB) | Bugs depend on entry state; unrecorded state makes "intermittent" out of "deterministic" | ch-4 |
| Intermittent bug being chased by re-running and eyeballing | Log everything on every run; diff a captured failing run against a passing run | Capture converts a 1-in-N failure into a fully-described case you can study every time | ch-4 |
| Fix "verified" by N passing reruns of a flaky sequence | Find the deterministic signature (condition → 100% fail); test until the signature occurs without failure | Statistical passes can't distinguish fixed from lucky | ch-4 |
| Engineer/agent responds to a report with "that can't happen" | Accept the data; make it fail in your presence; your assumed mechanism is what can't happen | The failure did happen; the report is evidence, the theory is not | ch-4 |
| Reasoning proceeds from the symptom description without observing the failing artifact | See the actual failure: the noticed symptom is the result, the failure is upstream | Well pump replaced for an air-compressor noise; server "crash" was the janitor's outlet | ch-5 |
| Debug instrumentation added, then results trusted immediately | Re-run the repro after instrumenting to prove the bug survived (Heisenberg) | Instrumentation perturbs timing/size/temperature and can hide the bug | ch-5 |
| "Can't rebuild production code, so swap modules at APIs to isolate" | Rebuild with debug output — you'll have to rebuild to fix it anyway | Module-swapping simulates the failure and dead-ends at module granularity | ch-5 |
| A guess is being *acted on* (fix written) rather than *checked* (probe placed) | Guess only to focus where to look next; confirm by observation before fixing | The measure of a debugger is how few bad guesses they act on | ch-5 |
| Cheap+likely fix available (bulb swap, restart, reinstall dep) but expensive fix being attempted on a guess | Try the cheap-likely fix without full diagnosis; never the expensive one | The one sanctioned guess-fix is the trivially cheap, highly likely one | ch-5 |
| Investigation verifies known-good components from the working end forward | Start at the observed failure and bisect upstream; probe branch points | Too many correct things to confirm; the bad path is short | ch-6 |
| Search converged on the boundary of the assumed scope without finding the bug | Widen the range — the bounding assumption was wrong | The bug was upstream of the assumed range (furnace, not water heater) | ch-6, ch-9 |
| Corruption invisible in production-like data | Inject a known easy-to-spot pattern; then re-verify the failure still occurs | `00 55 AA FF` made a doubled write instantly visible; random data hid it | ch-6 |
| Known unrelated-looking defect left in place during the hunt ("that can't affect this") | Fix known bugs immediately; fix noise-class bugs (races, reentrancy, uninitialized vars) first | Bugs hide and distort each other; noise-class defects destabilize everything downstream | ch-6 |
| Mid-debug diff contains cleanup/refactor of code not implicated in the failure | Leave working ugliness alone until the bug is fixed | Perfectionist fixes delay the investigation and change the system under test | ch-6 |
| Diff bundles multiple speculative changes | One change per experiment | Multi-change success leaves the cause unknown and routinely breaks other things | ch-7 |
| A change that didn't fix the bug is still present in the tree | Back it out immediately | "No effect on the bug" ≠ no effect; leftover changes corrupt later verification | ch-7 |
| Failing and passing runs captured under different machines/builds/days/params | Re-capture as identical consecutive runs; diff the logs | Every extra difference is noise you must hand-filter; the bug is in the difference | ch-7 |
| Regression in a previously working system, diff not consulted | Bisect versions to first-bad; verify last-good passes and first-bad fails; read that diff | Version control is the audit trail of the design | ch-7, ch-8 |
| Fix targets the change that *exposed* an old latent bug | Plug the hole, don't just revert the trigger (may revert short-term) | The subsystem had a hole; new conditions merely walked you to it | ch-7 |
| Multi-attempt debugging session with no written log of attempts/results | Record what you did, in what order, what happened — with timestamps | The insignificant detail (plaid shirt) is the key; memory drops it first | ch-8 |
| Bug report or handoff says "it's broken"/"see attached logs" without symptoms, magnitude, or which-log-is-which | Annotate: exact symptom, duration/magnitude, correlated timestamps, failing vs passing log labeled | Unannotated logs are a food diary without the hives | ch-8 |
| Deep component diagnosis begun without verifying foundations | Check the plug: right binary/branch/version running? service up? env var set? initialized? | Foundation assumptions are invisible and their bugs look otherworldly | ch-9 |
| Observation depends on an unverified tool (meter, script, debug print, simulator, CI harness) | Test the tool: prove it detects a known-good and known-bad case first | Dead-battery continuity checker; text-mode file reads; the emulator that didn't strip bit 8 | ch-9, ch-13 |
| Conditional debug print produced silence | Make prints unconditional with the condition's value in the output | Silence can't distinguish "event didn't happen" from "print is broken" | ch-9 |
| Solo grind past the point of progress; help not sought for pride | Ask early: insight, expertise (vendor/docs), or experience (someone who's seen it) | Explaining the problem alone often solves it; experience knows where to whack | ch-10 |
| Handoff/escalation opens with a theory | Report symptoms, conditions, and what's intermittent — withhold the theory | Theories drag the helper into your rut and filter the detail they needed | ch-10 |
| Diagnosis consists mainly of which module/team is "obviously" not at fault | Look instead of finger-pointing; want the bug in your own stuff | Thinking-as-finger-pointing actively prevents looking | ch-13 |
| "Fixed" claimed without re-running the original failing sequence | Re-run the exact repro against the fix | The $75 wire swap; testing under different conditions proves nothing | ch-11 |
| Fix verified, but other changes landed alongside it | Cycle fixed→broken→fixed: remove the fix, see it fail; restore, see it pass | Otherwise an incidental change may be the "fix", and it won't ship with the patch | ch-11 |
| Issue closed as "can't reproduce anymore" | It never goes away by itself; re-derive the repro, or ship a field trap that captures full context on recurrence | The conditions changed, not the bug; it returns at a customer | ch-11 |
| Failed part/process replaced without asking why it failed | Fix the cause before (or with) the replacement; then consider fixing the process that produced it | New transformers keep smoking while the short remains; next machine gets two bolts again | ch-11 |
| Remote debugging: instruction issued, user answers "yes, done" | Have them narrate what they did in their own words; label artifacts for them | Users answer yes regardless; they misunderstood the first time too | ch-14 |
| Unexplained-but-smelly observation omitted from a report for lack of a causal story | Report it anyway, flagged as unexplained | You don't have to be sure; the shirt being plaid mattered | ch-10 |

## Anti-patterns

- **Thinker's shortcut** — root-causing from the armchair. Cue: causal claims ("it must be the X because…") with zero attached observations; a fix diff appearing before any instrumentation diff. (ch-5)
- **Simulating the failure** — rebuilding a guessed mechanism or a "seemingly identical" environment and studying that. Cue: plan contains "set up an equivalent system" while the failing one is accessible; new test rig fails in a *different* way and the investigation follows the new failure. (ch-4)
- **Shotgun debugging** — changing several things and celebrating "it works now". Cue: multi-hunk speculative diff; commit message "try fixing X"; no statement of which change mattered. (ch-7)
- **Leftover experiment** — the non-fix that stays in. Cue: working tree contains changes from disproven hypotheses during continued debugging. (ch-7)
- **Wubba fix** — credit assigned to your change when a concurrent change did the work. Cue: fix verified only in an environment that received other changes; no remove-the-fix re-break test. (ch-11)
- **"It went away"** — closure by non-reproduction. Cue: issue closed with "no longer reproduces", no cause identified, no field trap added. (ch-11)
- **Finger-pointing diagnosis** — the conclusion is about whose code it isn't. Cue: "must be in <other module/team>" with the same evidence the other side is using for the converse; nobody has looked. (ch-13)
- **Trusting the rig** — treating a simulator/emulator/mock/CI harness as ground truth. Cue: "passes on the emulator" cited against a real-environment failure report; the test double is more permissive than the real dependency (the bit-8 emulator). (ch-9, ch-13)
- **Square-three start** — debugging behavior before verifying startup/foundations. Cue: hours into internals before confirming the right code is deployed/loaded/restarted, config present, service actually running. (ch-9)
- **Theory-poisoned handoff** — escalation that transmits conclusions instead of observations. Cue: the help request's first paragraph is a hypothesis; symptoms appear only as support for it. (ch-10)
- **Statistical self-deception** — flaky-failure conclusions from tiny samples ("fails more when…", "0 of 28 since the fix"). Cue: frequency claims without a captured always/never discriminator. (ch-4)
- **Bug-report vagueness** — "it's broken", unlabeled logs, no magnitudes, no timestamps. Cue: report can't be turned into a repro or a correlation by a stranger. (ch-8)

## Applicability & exemptions

- **Scope guard**: the book governs the interval from accepted bug report to verified fix. It explicitly does not cover prevention (reviews, process), detection (test design, coverage), or triage (whether/when to fix) — don't fire these rules at test-strategy or prioritization decisions.
- **Cheap-likely exception to "look before fixing"** (ch-5): when a cause is both highly probable and trivially cheap to try (swap bulb, restart service, bump a known-bad dependency), trying the fix *is* the look. Fails the exemption if the fix is expensive or invasive (the in-sink fuse story).
- **Fixed→broken→fixed exemption** (ch-11): re-breaking applies to *design* fixes (code, schematics). For repaired instances (replaced part, restored file, reinstalled machine) re-breaking is unnecessary and sometimes dangerous.
- **Destructive/painful repros** (ch-4): "make it fail again and again" is bounded by damage — alter the minimum needed to make repetition safe, and note the alteration.
- **"Fix the noise first" is bounded** (ch-6): it covers defect classes known to destabilize (races, reentrancy, uninitialized state, glitchy clocks). It is *not* a license for mid-hunt refactoring; Agans explicitly exempts working-but-ugly code (GOTOs) from cleanup during debugging — a deliberate tension with this directory's refactoring sources, resolved by phase: hunt now, clean after.
- **"Don't trust statistics" ≠ ignore correlations**: captured always/never associations in logs are exactly what to pursue; only small-sample frequency impressions are banned.
- **Simulation is partially rehabilitated** for one purpose: reproducing a bug on a *second* system proves it's a design bug and narrows config-dependence. The ban is on modifying the simulation until it fails, and on studying the simulation when the failing original is available.
- **Systems that resist the method**: Agans names domains too complex or unownable to debug this way (his joke: the economy) and warns against debugging outside your fundamentals (games programmer vs nuclear plant) — the fallback is Rule 8, get someone with the fundamentals.
- **Help-desk/remote mode** (ch-14) is troubleshooting under proxy: prefer workaround-now + escalated bug report over heroic remote root-causing; full reinstall is a legitimate last resort *because* it establishes a known base state, at the cost of destroying evidence.

## Candidate lexicon rows

| fix or diff proposed before the failure has been reproduced (no failing command/test/log cited) | **Make It Fail** — an unreproduced bug can't be observed while failing and the fix can't be verified, only lucky | Can I run one recorded sequence right now that demonstrates the failure? | blocker | plan | src: debugging-9-rules ch-4 |
| root-cause claim with no attached observation (no log line, trace, breakpoint, or good-vs-bad diff) | **Quit Thinking and Look** — guessed mechanisms usually fix something that isn't broken and can mask the real bug | What did I actually see failing, as opposed to infer? | blocker | review | src: debugging-9-rules ch-5 |
| plan rebuilds a "similar" environment or mocks the suspected mechanism while the failing system is reachable | **Stimulate, Don't Simulate** — the copy differs in the one condition that matters; it works flawlessly or fails a new, distracting way | Am I amplifying the real failure's conditions, or re-creating my guess elsewhere? | should | plan | src: debugging-9-rules ch-4 |
| diff bundles multiple speculative changes "to see if it helps" | **Rifle, Not Shotgun** — a multi-change success leaves the cause unknown and the extra changes routinely break other things | Which single variable does this experiment test? | should | write | src: debugging-9-rules ch-7 |
| an experimental change that didn't fix the bug remains in the working tree | **Back Out the Non-Fix** — a change with no effect on the bug still changed behavior and will corrupt verification of the real fix | Have I reverted every disproven experiment before this next one? | blocker | write | src: debugging-9-rules ch-7 |
| multi-attempt debugging with no written record of steps, order, and results | **Keep an Audit Trail** — the insignificant-seeming detail is reliably the key, and memory drops it first | Could someone else reconstruct what I tried and what happened, with timestamps? | should | write | src: debugging-9-rules ch-8 |
| component internals investigated before verifying foundations (right binary/branch deployed, service running, env/config present, tool sane) | **Check the Plug** — foundation assumptions are invisible while debugging details, and their violations look otherworldly | Am I certain I'm running the code and config I think I am — and does my measuring tool pass a known-good/known-bad check? | should | plan | src: debugging-9-rules ch-9 |
| escalation or sub-agent handoff opens with a theory instead of symptoms, conditions, and intermittency | **Report Symptoms, Not Theories** — transmitted theories drag the helper into your rut and your bias filters out the detail they needed | If I deleted my hypothesis, does the report still fully describe what was observed? | should | review | src: debugging-9-rules ch-10 |
| "fixed" declared without re-running the original failing sequence against the fix | **If You Didn't Fix It, It Ain't Fixed** — testing under different conditions proves nothing about the bug you had | Did the exact repro that failed before now pass? | blocker | review | src: debugging-9-rules ch-11 |
| fix verified only alongside other concurrent changes; no re-break test | **Fixed→Broken→Fixed** — an incidental change may be the real "fix", and it won't ship with your patch | Does removing only my fix bring the failure back? | should | review | src: debugging-9-rules ch-11 |
| issue closed as "can't reproduce anymore" with no cause found | **It Never Goes Away by Itself** — the conditions changed, not the bug; it returns in the field | If I can't reproduce it, what trap did I leave to capture it when it recurs? | blocker | review | src: debugging-9-rules ch-11 |
| investigation verifies known-good components forward from the working end | **Start with the Bad** — there are too many correct things to confirm; bisect upstream from the observed failure | Am I probing the failure path's midpoint, or admiring parts that work? | judgment | plan | src: debugging-9-rules ch-6 |
