# golden.json label review — after agent visual pass (2026-07-06)

A full visual pass (all 38 scenes vs the 18 entity crops) replaced the filename
heuristics. High-confidence resolutions applied directly to `golden.json`:
`ccqw-*` → Caitlin Weaver (race bib "CAITLIN" in ccqw-running); `mcm-*` +
`Breiðamerkurjökull` → Maria Correonero (same trip/outfit as mcm-icecave, ombré
hair matches crop); `k.mcc-1` → Kirstie Mccarrel (sash woman matches crops);
`example-ellynheald-goldleaf` → Ellyn Heald; `liam-maloney-painting` → [] (a
painting, not a person); `nina-machiavelli` → [] (a dog); `rrw-mirror` → []
(stranger — watermark reads @rachelrabbitwhite, not Ryann).

## Rows still needing operator adjudication (edit `present_identities`, then delete this file)

- [ ] `cristina-1.jpg` — set to [Caitlin?, Cristina?, Kirstie?]: three women at a
  party. Middle (sheep hood, pale, blonde braids) reads as Kirstie; right (dark
  hair, full bangs, blue lips) reads as Caitlin; LEFT (dark high pony, pink
  fishnet, tattoos) assumed Cristina from filename but does NOT resemble her
  platinum-pixie crop. Confirm all three.
- [ ] `kirstie-1.jpeg` — set to [Kirstie]: warm-blonde woman with dog + blue
  eyes + nose stud, rounder-faced than Kirstie's other shots; could be Erika.
- [ ] `kirstie-boat.jpg` / `kirstie-boat_detected.jpg` — set to [Erika?, Kirstie]:
  right (pink bucket hat, floral arm tattoos) is clearly Kirstie; LEFT (red
  swimsuit, warm blonde, sunglasses) assumed Erika — confirm. Boat driver in
  background = stranger.
- [ ] `ccqw-erika.jpg` — set to [Caitlin, Erika]: foreground blonde assumed
  Erika; woman in red + man in mirror — is the red-shirt woman Caitlin, or a
  stranger? Confirm the pair.
- [ ] `ryann-group-party.jpg` — set to [Ryann]: six women in pink satin PJs;
  confirm which (if any others) are roster members.
- [ ] `mcm-eye-blocked.jpg` — set to [Maria]: stylized blue-lit portrait, hair
  up, dark lips, Rubik-cube prop; face consistent with Maria but least certain
  of the mcm set.
- [ ] `ryann-party.jpg` — set to [Ryann]: left blonde matches Ryann's png crop;
  right dark-haired woman assumed stranger — confirm.

Stranger faces (correct as absent, useful for true-rejection accounting):
ccqw-running (bearded runner, bib "BEN…"), k.mcc-1 (glasses+face-gems woman),
maria-cocktail (3), maria-party (2), ryann-party (1), boat driver, rrw-mirror
(1), ccqw-underexposed background pedestrian.
