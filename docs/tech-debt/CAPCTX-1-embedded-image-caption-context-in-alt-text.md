# Tech Debt: CAPCTX-1 embedded image captions (IPTC) compose alt text unattributed and unfiltered

**Status:** deferred, behaviour is working as designed · **Owner:** description service (GPU prompt, fusion) + plugin (ContextPack assembly) · **Origin:** 2026-10-16 investigation of demo attachment 16 (`demo.altcontext.com`). Prior art on the same channel: DEMOLIVE-1 finding 10161 (filename leak). Recommendations cite Canon v0.26.2.

## What happens today

1. On upload, WordPress core (`wp_read_image_metadata`) copies IPTC title (2#005) into `post_title` and IPTC caption (2#120) into `post_excerpt`.
2. `build_context_pack()` in `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php` sends both as `context_pack.attachment.title` and `.caption`. The caption is bounded to 500 chars. This happens whenever `attachment` is in `acx_description_context_categories`, which it is by default.
3. `_SYSTEM_PROMPT` in `apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py` tells the model to "describe only what is visible". It also tells the model to "weave the people's names and factual details it supplies into the description".

Attachment 16 carries a Keystone agency caption in German: name, "Portrait vom Mai 1953", licensing boilerplate, account number and a keyword list. The published alt text is: "Audrey Hepburn smiles in a black-and-white portrait from May 1953, …". The name and the date are stated as if the frame shows them.

## Gaps

### 1. Record-sourced names bypass the identity-naming policy

The tenant identity-naming policy (`build_identity_context`) and the metadata category allowlist are separate controls. Any name in title, caption or filename reaches the model. The prompt then lets the context decide naming ("never name … anyone the context does not name"). The result is that untrusted evidence settles a policy question.

Canon:
- [FM-01] **Instruction-authority contract**: keep lower-authority content out of policy position. Source: AI Engineering. The caption is untrusted evidence. Whether a name may be emitted is policy. The naming gate must govern every name source, not only recognition.
- [ATTRIB-05] **Honor source identity decisions**: when the record supplies a name, use it. Source: Regarding the Pain of Others, ch. 5. Do not strip record names wholesale. Where policy permits naming, the record's name stands.
- [ATTRIB-02] **Captions explain or falsify identity**: put uncited identity in EDITORIAL or cited-source voice, or drop it. Source: Regarding the Pain of Others, ch. 1. CARD-18 (attribute-claims-to-their-bearer) exempts a named record only through the citation.
- [ATTRIB-10] **Name subjects to creator depth** (S·e) limits naming by "living-person and surveillance risk". Source: Anti-Racist Description Resources. Whether record names of living people follow the tenant naming switch is a judgment call for the product. Canon does not settle it.

Recommendation: route record-sourced names through the same naming decision point as recognised identities. When the gate allows a name, phrase it as the record's claim, not as what the frame shows. When the gate denies it, keep the visible description and drop the name.

### 2. Off-frame facts (the date) are asserted as image content

The two prompt instructions conflict. The model resolved the conflict by stating the caption's date as visible fact.

Canon:
- [BOUND-01] **Assertable set is bounded**: when a contextual caption interprets a still, mark that context as editorial and do not treat it as the image's own proof. Source or drop off-frame claims. Source: Ways of Seeing, ch. 1 + On Photography + Regarding the Pain of Others, ch. 8 + Image Music Text, ch. 3 + The Civil Contract of Photography, ch. 6 + Under the Sign of Saturn, §syberbergs-hitler.
- [WRIT-26] **Restore a needed attribution** (B·v). Source: The Sense of Style, ch. 2. CARD-18, steps 2 and 7: name the bearer of every non-visual claim; with no bearer, cut the clause.
- [PROV-01] **Every output walks back to its evidence** (B·w). Source: Model Cards + AI Engineering. Each context-sourced clause must trace to the field it came from. Fusion already tags `FactSource.ATTACHMENT` (`reconcile.py` `_reconcile_caption_facts`), but the GPU prose path does not carry that tag into the output.

Recommendation: change the prompt so visible content is stated plainly and off-frame context facts (date, place, event) are either attributed to the record ("captioned as a May 1953 portrait") or omitted. The prompt must not instruct both "only visible" and "weave in".

### 3. Agency captions reach the model raw and are cut at 500 chars

Licensing text, account numbers and keyword lists use up the caption budget. `bounded_string` then cuts the caption mid-text, without any signal. In this case the decisive facts sat at the start of the caption, so they survived the cut. Captions that put them at the end lose them.

Canon:
- [FM-02] **Context is a budget**: never let appending inputs silently truncate instructions or decisive evidence. Source: AI Engineering.
- [FM-01] (above): the `<<<CONTEXT>>>` markers and the "not instructions" line already keep the caption in evidence position. Keep that, and do not promote it.

Recommendation: before bounding, strip known agency boilerplate (licensing notices, account and ID numbers, keyword tails). Also prefer IPTC's structured fields (by-line, date created, location) over free-text parsing, truncate at a sentence or field boundary, and record when truncation happened.

## Verification (CARD-23, context-obedience-is-a-separate-capability)

- Add a fixture for this attachment's metadata and run two fixed arms on it: no context and context supplied. Score the context arm on insertion, non-contradiction and non-invention of supplied facts. Select prompt changes on that arm, not on how fluent the no-context arm reads.
- In the context arm, check that every name and date is either attributed to the record or absent (CARD-18 verification: "can a second viewer falsify this sentence from the image alone? If no, require source tag or cut").
- Test that turning the naming gate off removes record-sourced names while the visible description stays.

## Why it's safe to defer

- The system behaves as designed, and this output is factually right for this image.
- An off switch exists: removing `attachment` from `acx_description_context_categories`. It also drops title, filename and description context.
- The project is greenfield and has no production users.

## Trigger

Pick up before the E15 public demo launch is signed off, or with the next change to `_SYSTEM_PROMPT` or `build_context_pack()`, whichever comes first.
