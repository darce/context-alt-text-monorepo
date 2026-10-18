# Image-only caption service sample

Service: https://imagecaptiongenerator.com/alt-text-generator
Date: 2026-09-09. UI model: Gemini 3.1 Flash Lite. Tone: Alt Text.
Language: English (US). Additional Info: empty. Uploaded the bundled
guided-press-tribeca-2026.jpg bytes under the neutral filename sample.jpg.
No roster, names, page title or source caption was supplied. No account/payment.

The first result (verbatim) was the 0.0.12 demo starting alt text:

> Canadian Prime Minister Justin Trudeau and singer Katy Perry posing together on the red carpet at the Tribeca Festival.

All five suggestions named both people. This sample therefore does not support
the claim that a regular caption service returns “Two people at a film festival.”
The provider exposes a model label; we did not independently verify its backend.
The sample is not a representative benchmark. The wording is preserved for
editorial review, including its title for Trudeau. Source caption and this
third-party output are separate provenance. The live UI names the provider,
model label, date and absence of supplied context.

## AltText.ai sample — selected baseline for 0.0.13

At the user’s request, submitted the same bundled bytes as sample.jpg through
https://alttext.ai/ “Try It”, with optional custom SEO keywords empty, no names
and no context. No account or plugin installation was needed. The public UI
did not identify its underlying model. Result (verbatim):

> A man in a black suit and a woman in a white dress pose together, smiling, in front of a Tribeca Festival step-and-repeat backdrop.

Neither person was named. The demo uses this exact result and explicitly names
AltText.ai’s free web demo, not a WordPress plugin run. The plugin listing says
it relies on the AltText.ai API, but this test did not verify plugin parity.
The other service’s named results remain above: these are two individual
observations, not evidence that all regular image services omit names.

Validation for the selected baseline: focused workflow/state/accessibility
tests and production build; live desktop/mobile apply and undo verification.
Plugin releases retain the prior version as a rollback copy on the demo VM.

The 0.0.13 accessibility run exceeded its default 5-second per-test budget;
all 16 cases passed with a 15-second CLI timeout. The other 92 focused tests
passed with default settings. No test assertions were relaxed.
