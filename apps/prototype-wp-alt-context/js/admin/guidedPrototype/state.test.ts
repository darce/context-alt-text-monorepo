import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, describe, expect, it, vi } from 'vitest';

import { guidedCopy } from './copy';
import {
  applyGuidedDraft,
  canApply,
  canPreview,
  canRestoreRevision,
  canUndo,
  cancelGuidedChoiceReplacement,
  chooseGuidedName,
  confirmGuidedChoiceReplacement,
  createGuidedDemoState,
  createGuidedScenario,
  editGuidedDraft,
  getGuidedFace,
  getGuidedPerson,
  GUIDED_DRAFT_ORIGIN,
  GUIDED_DRAFT_STATUS,
  GUIDED_NAME_CHOICE,
  GUIDED_OUTCOME,
  GUIDED_PERSON_KEYS,
  GUIDED_STEP,
  guidedDraftKeyFor,
  guidedNameCoverage,
  guidedSampleFor,
  guidedStepIndex,
  keepGuidedCurrentAltText,
  namesDecided,
  previewGuidedDraft,
  resetGuidedDemoState,
  restoreGuidedRevision,
  retryGuidedFixture,
  selectGuidedStep,
  undoGuidedApplication,
  type GuidedDemoState,
  type GuidedImageKey,
  type GuidedNameChoice,
  type GuidedSampleKey,
  type GuidedScenario,
} from './state';

const KATY = 'katy-perry';
const JUSTIN = 'justin-trudeau';
const ORIGINAL_ALT = 'A man in a black suit and a woman in a white dress pose together, smiling, in front of a Tribeca Festival step-and-repeat backdrop.';

const INCLUDE = GUIDED_NAME_CHOICE.INCLUDE;
const OMIT = GUIDED_NAME_CHOICE.OMIT;
const UNDECIDED = GUIDED_NAME_CHOICE.UNDECIDED;
const TRIBECA: GuidedImageKey = 'tribeca';
const COACHELLA: GuidedImageKey = 'coachella';

const withMissingSample = (
  scenario: GuidedScenario,
  imageKey: GuidedImageKey,
  key: GuidedSampleKey,
): GuidedScenario => {
  const samples = { ...scenario.samples[imageKey] };
  delete samples[key];
  return {
    ...scenario,
    samples: {
      ...scenario.samples,
      [imageKey]: samples,
    },
  };
};

const chooseBoth = (
  state: GuidedDemoState,
  scenario: GuidedScenario,
  left: GuidedNameChoice,
  right: GuidedNameChoice,
  imageKey: GuidedImageKey = TRIBECA,
): GuidedDemoState =>
  chooseGuidedName(
    chooseGuidedName(state, scenario, 'left', left, imageKey),
    scenario,
    'right',
    right,
    imageKey,
  );

const includeBoth = (scenario: GuidedScenario, state: GuidedDemoState = createGuidedDemoState()): GuidedDemoState =>
  chooseBoth(state, scenario, INCLUDE, INCLUDE);

const snapshot = (value: unknown): string => JSON.stringify(value);

describe('guided scenario fixture', () => {
  it('starts from a saved run with two labelled people, two matched faces and no demo decisions', () => {
    const scenario = createGuidedScenario();

    expect(scenario.origin).toBe('saved-build');
    expect(scenario.scenarioVersion).toBe('guided-people-v5');
    expect(GUIDED_PERSON_KEYS).toEqual([KATY, JUSTIN]);
    expect(scenario.people.map((person) => person.key)).toEqual([KATY, JUSTIN]);
    expect(scenario.faces.map((face) => [face.id, face.position])).toEqual([
      ['tribeca-justin-trudeau', 'left'],
      ['tribeca-katy-perry', 'right'],
      ['coachella-justin-trudeau', 'left'],
      ['coachella-katy-perry', 'right'],
    ]);
    expect(scenario.pressPhotos.map((photo) => photo.key)).toEqual(['tribeca', 'coachella']);
    expect(scenario.pressPhoto).toBe(scenario.pressPhotos[0]);
    expect(scenario.pageContext.runDate).toBe('2026-09-10');
    expect(scenario).not.toHaveProperty('identities');
    expect(scenario).not.toHaveProperty('candidate');
    expect(scenario).not.toHaveProperty('appliedText');
    expect(scenario).not.toHaveProperty('history');
    expect(scenario).not.toHaveProperty('drafts');

    expect(getGuidedPerson(scenario, KATY)).toMatchObject({
      name: 'Katy Perry',
      clusterId: '68adc97c-f81f-42c3-9e5c-061f16770361',
      savedPhotoCount: 5,
    });
    expect(getGuidedPerson(scenario, KATY).galleryPhotos.map((photo) => photo.credit)).toEqual([
      'Justin Higuchi, CC BY 4.0, resized',
      'Glenn Francis (Toglenn), CC BY-SA 4.0, resized',
      'Voice of America, public domain',
    ]);
    expect(getGuidedPerson(scenario, JUSTIN)).toMatchObject({
      name: 'Justin Trudeau',
      clusterId: 'fd0d2b5d-108a-42b7-af25-f028e40d5778',
      savedPhotoCount: 3,
    });
    expect(getGuidedPerson(scenario, KATY).galleryPhotos.map((photo) => photo.src)).toEqual([
      expect.stringContaining('guided-katy-perry-2026'),
      expect.stringContaining('guided-katy-perry-2019'),
      expect.stringContaining('guided-katy-perry-2016'),
    ]);
    const justinPhotos = getGuidedPerson(scenario, JUSTIN).galleryPhotos;
    expect(justinPhotos).toHaveLength(3);
    expect(justinPhotos.map((photo) => photo.src)).toEqual([
      expect.stringContaining('guided-justin-trudeau-2025'),
      expect.stringContaining('guided-justin-trudeau-2023'),
      expect.stringContaining('guided-justin-trudeau-2024'),
    ]);
    expect(justinPhotos.every((photo) => photo.src.trim() !== '')).toBe(true);
    expect(new Set(justinPhotos.map((photo) => photo.src)).size).toBe(justinPhotos.length);
    expect(justinPhotos.map((photo) => photo.credit)).toEqual([
      '© European Union, 2025, EU reuse licence, resized',
      'Lea-Kim Chateauneuf, CC BY-SA 4.0, resized',
      'Jonathan Miranda / Presidencia de la República del Ecuador, public domain',
    ]);
    for (const person of scenario.people) {
      expect(person.galleryPhotos.length).toBeLessThanOrEqual(person.savedPhotoCount);
      for (const photo of person.galleryPhotos) {
        expect(photo.altText).toContain(person.name);
        expect(photo.credit).not.toBe('');
      }
    }

    expect(getGuidedFace(scenario, JUSTIN)).toEqual({
      id: 'tribeca-justin-trudeau',
      imageKey: 'tribeca',
      position: 'left',
      box: { x: 513, y: 76, width: 133, height: 189 },
      matchedPersonKey: JUSTIN,
      similarity: 0.8938,
      strength: 'strong',
      source: 'saved-run',
    });
    expect(getGuidedFace(scenario, KATY)).toEqual({
      id: 'tribeca-katy-perry',
      imageKey: 'tribeca',
      position: 'right',
      box: { x: 706, y: 139, width: 121, height: 182 },
      matchedPersonKey: KATY,
      similarity: 1,
      strength: 'strong',
      note: 'Her face is turned a little to the side.',
      source: 'saved-run',
    });

    expect(scenario.pressPhoto.src).toContain('guided-press-tribeca-2026');
    expect(scenario.pressPhoto.altText).toBe(ORIGINAL_ALT);
    expect(scenario.pressPhoto.credit).toBe('Colleen Sturtevant, CC BY-SA 4.0, resized');
    expect(scenario.pressPhoto.event).toBe('Tribeca Festival, New York, June 2026');
    expect(scenario.pressPhotos[0].altContextDescription).toEqual({
      text: 'Justin Trudeau and Katy Perry pose together on the red carpet at the Tribeca Festival in New York in June 2026. Trudeau is wearing a black tuxedo with a white shirt, while Perry is in a white sleeveless dress with a draped design. They are standing in front of a backdrop with the Tribeca Festival and 10 Lives Studios logos.',
      system: 'altcontext.com',
      systemUrl: 'https://altcontext.com/',
      generatedOn: '2026-09-10',
    });
    expect(scenario.pressPhotos[1]).toMatchObject({
      key: COACHELLA,
      credit: 'https://www.instagram.com/katyperry/',
      source: 'https://www.instagram.com/katyperry/',
      altTextAiCaption: {
        text: 'Two people sit on a curb outdoors at night, holding red cups and eating food. Both appear relaxed and casually dressed, with trees and plants in the background.',
        providerUrl: 'https://alttext.ai/',
        capturedOn: '10 September 2026',
      },
    });
    expect(scenario.pressPhotos[1].altContextDescription).toEqual({
      text: 'Justin Trudeau and Katy Perry are sitting together outdoors at night, eating from red cups and a yellow noodle container. Trudeau wears a white t-shirt, blue jeans, and a backward blue cap, while Perry wears a white t-shirt, black boots, and holds a red cup. They are surrounded by plants and appear to be at a casual evening event.',
      system: 'altcontext.com',
      systemUrl: 'https://altcontext.com/',
      generatedOn: '2026-09-10',
    });
    expect(scenario.provenance).toEqual({
      service: 'AltContext recognition service (production)',
      model: 'InsightFace buffalo_l',
      runDate: '2026-09-10',
      threshold: 0.6,
      note: 'Saved from a production run. The demo does not run recognition live.',
      alsoChecked:
        'The production run also grouped the bundled Coachella press photo of the same two people. Its source is Katy Perry’s Instagram account; no formal reuse licence is recorded.',
    });
    expect(scenario.visualFacts).toHaveLength(4);
    expect(scenario.samples[TRIBECA].none).not.toMatch(/Katy Perry|Justin Trudeau/);
  });

  it('keeps every bundled photo credit complete and marks Creative Commons edits', () => {
    const scenario = createGuidedScenario();
    const credits = [
      scenario.pressPhoto.credit,
      ...scenario.people.flatMap((person) => person.galleryPhotos.map((photo) => photo.credit)),
    ];

    for (const credit of credits) {
      expect(credit.trim()).not.toBe('');
      expect(credit).toMatch(/CC BY|public domain|EU reuse licence/);
      if (credit.includes('CC BY')) {
        expect(credit).toMatch(/resized$/);
      }
    }
    expect(scenario.pressPhotos[1].credit).toBe('https://www.instagram.com/katyperry/');
  });

  it('keeps every recorded sample coherent: names only where included, visual details everywhere', () => {
    const { samples } = createGuidedScenario();
    const tribecaSamples = samples[TRIBECA];
    const coachellaSamples = samples[COACHELLA];

    expect(tribecaSamples.both).toBe(
      "Justin Trudeau and Katy Perry pose together on the red carpet at the Tribeca Festival, standing in front of a backdrop with the event's logo. Trudeau is wearing a black tuxedo with a white shirt, while Perry is in a white sleeveless dress with a draped design. Perry has her arm around Trudeau and is smiling, showing off a ring on her left hand.",
    );
    expect(tribecaSamples['katy-perry']).toContain('Katy Perry');
    expect(tribecaSamples['katy-perry']).not.toContain('Justin Trudeau');
    expect(tribecaSamples['justin-trudeau']).toContain('Justin Trudeau');
    expect(tribecaSamples['justin-trudeau']).not.toContain('Katy Perry');
    for (const text of Object.values(tribecaSamples)) {
      expect(text).toContain('Tribeca Festival');
      expect(text).toContain('hand');
    }
    expect(coachellaSamples).toEqual({
      none: 'A man and a woman are sitting together outdoors at night, eating from red cups and a yellow container of noodles. The man, wearing a white t-shirt and blue jeans, holds chopsticks and a cup, while the woman, in a white top and black boots, eats from a cup. They are surrounded by plants and trees in a relaxed, casual setting.',
      both: 'Justin Trudeau and Katy Perry are sitting together outdoors at night, eating from red cups and a yellow noodle container. Trudeau wears a white t-shirt, blue jeans, and a backward blue cap, while Perry wears a white t-shirt, black boots, and holds a red cup. They are surrounded by plants and appear to be at a casual evening event.',
    });
    expect(coachellaSamples).not.toHaveProperty('katy-perry');
    expect(coachellaSamples).not.toHaveProperty('justin-trudeau');
  });

  it('counts only bundled reference photos per person', () => {
    expect(guidedNameCoverage(createGuidedScenario())).toEqual([
      { key: KATY, shown: 3, total: 5 },
      { key: JUSTIN, shown: 3, total: 3 },
    ]);
  });

  it('does not mutate the fixture when a demo state is created or advanced', () => {
    const scenario = createGuidedScenario();
    const before = snapshot(scenario);
    const state = includeBoth(scenario);
    editGuidedDraft(state, 'Katy Perry waves.');
    expect(snapshot(scenario)).toBe(before);
  });
});

describe('createGuidedDemoState', () => {
  it('uses the brief initial fields and omits live* state', () => {
    const state = createGuidedDemoState();
    expect(state).toEqual({
      activeStep: GUIDED_STEP.CONTEXT,
      choices: { left: UNDECIDED, right: UNDECIDED },
      draftText: null,
      draftOrigin: GUIDED_DRAFT_ORIGIN.NONE,
      draftStatus: GUIDED_DRAFT_STATUS.BLOCKED,
      draftVersion: 0,
      previewedVersion: null,
      draftHistory: [],
      pendingChoiceChange: null,
      appliedAltText: ORIGINAL_ALT,
      applicationUndoStack: [],
      outcome: GUIDED_OUTCOME.NOT_FINISHED,
      actionHistory: [],
    });
    expect(state).not.toHaveProperty('liveStatus');
    expect(state).not.toHaveProperty('liveRequestToken');
    expect(state).not.toHaveProperty('liveText');
    expect(state).not.toHaveProperty('liveContractVerified');
  });
});

describe('selectors', () => {
  it.each([
    [{ left: UNDECIDED, right: UNDECIDED }, null],
    [{ left: INCLUDE, right: UNDECIDED }, null],
    [{ left: UNDECIDED, right: INCLUDE }, null],
    [{ left: OMIT, right: UNDECIDED }, null],
    [{ left: UNDECIDED, right: OMIT }, null],
    [{ left: INCLUDE, right: INCLUDE }, 'both'],
    [{ left: INCLUDE, right: OMIT }, 'justin-trudeau'],
    [{ left: OMIT, right: INCLUDE }, 'katy-perry'],
    [{ left: OMIT, right: OMIT }, 'none'],
  ] as const)('guidedDraftKeyFor(%j) -> %s', (choices, expected) => {
    expect(guidedDraftKeyFor(choices)).toBe(expected);
  });

  it('guidedSampleFor returns the matching recorded sample or null', () => {
    const scenario = createGuidedScenario();
    expect(guidedSampleFor(scenario, { left: UNDECIDED, right: INCLUDE })).toBeNull();
    expect(guidedSampleFor(scenario, { left: INCLUDE, right: INCLUDE })).toBe(scenario.samples[TRIBECA].both);
    expect(guidedSampleFor(scenario, { left: OMIT, right: OMIT }, COACHELLA)).toBe(scenario.samples[COACHELLA].none);
    expect(guidedSampleFor(scenario, { left: INCLUDE, right: INCLUDE }, COACHELLA)).toBe(
      scenario.samples[COACHELLA].both,
    );
    expect(guidedSampleFor(withMissingSample(scenario, TRIBECA, 'none'), { left: OMIT, right: OMIT })).toBeNull();
    expect(guidedSampleFor(scenario, { left: INCLUDE, right: OMIT }, COACHELLA)).toBeNull();
  });

  it('guidedStepIndex is the 0-based order of the four steps', () => {
    expect(guidedStepIndex(GUIDED_STEP.CONTEXT)).toBe(0);
    expect(guidedStepIndex(GUIDED_STEP.NAMES)).toBe(1);
    expect(guidedStepIndex(GUIDED_STEP.DRAFT)).toBe(2);
    expect(guidedStepIndex(GUIDED_STEP.APPLY)).toBe(3);
  });
});

describe('derived guards', () => {
  it('namesDecided requires both left and right to differ from undecided', () => {
    const start = createGuidedDemoState();
    const scenario = createGuidedScenario();
    expect(namesDecided(start)).toBe(false);
    expect(namesDecided(chooseGuidedName(start, scenario, 'left', INCLUDE))).toBe(false);
    expect(namesDecided(includeBoth(scenario, start))).toBe(true);
    expect(namesDecided(chooseBoth(start, scenario, OMIT, OMIT))).toBe(true);
  });

  it('canPreview requires decided names, ready status, and non-empty trimmed text', () => {
    const scenario = createGuidedScenario();
    const start = createGuidedDemoState();
    expect(canPreview(start)).toBe(false);
    const ready = includeBoth(scenario, start);
    expect(canPreview(ready)).toBe(true);
    expect(canPreview(editGuidedDraft(ready, '   '))).toBe(false);
    expect(canPreview(editGuidedDraft(ready, ''))).toBe(false);
    const missing = chooseBoth(start, withMissingSample(scenario, TRIBECA, 'both'), INCLUDE, INCLUDE);
    expect(missing.draftStatus).toBe(GUIDED_DRAFT_STATUS.FIXTURE_MISSING);
    expect(canPreview(missing)).toBe(false);
  });

  it('canApply requires a current preview, a changed string, and no pending choice', () => {
    const scenario = createGuidedScenario();
    const ready = includeBoth(scenario);
    expect(canApply(ready)).toBe(false);
    const previewed = previewGuidedDraft(ready);
    expect(canApply(previewed)).toBe(true);
    const edited = editGuidedDraft(previewed, 'Changed after preview.');
    expect(canApply(edited)).toBe(false);
    const pending = chooseGuidedName(editGuidedDraft(ready, 'Visitor text.'), scenario, 'right', OMIT);
    expect(pending.pendingChoiceChange).not.toBeNull();
    expect(canApply(previewGuidedDraft(pending))).toBe(false);
  });

  it('canApply compares draft and applied text without trimming', () => {
    const scenario = createGuidedScenario();
    const padded = `${ORIGINAL_ALT} `;
    const edited = editGuidedDraft(includeBoth(scenario), padded);
    expect(canApply(previewGuidedDraft(edited))).toBe(true);
  });

  it('canUndo is true only when the application stack is non-empty', () => {
    const scenario = createGuidedScenario();
    const start = createGuidedDemoState();
    expect(canUndo(start)).toBe(false);
    const applied = applyGuidedDraft(previewGuidedDraft(includeBoth(scenario, start)));
    expect(canUndo(applied)).toBe(true);
    expect(canUndo(undoGuidedApplication(applied))).toBe(false);
  });

  it('canRestoreRevision compares choice enum values, not object identity', () => {
    const scenario = createGuidedScenario();
    const edited = editGuidedDraft(includeBoth(scenario), 'First manual draft.');
    const confirmed = confirmGuidedChoiceReplacement(chooseGuidedName(edited, scenario, 'right', OMIT), scenario);
    const revision = confirmed.draftHistory[0];
    expect(revision).toBeDefined();
    const matching = chooseGuidedName(confirmed, scenario, 'right', INCLUDE);
    expect(matching.choices).not.toBe(revision.choices);
    expect(canRestoreRevision(matching, revision.revisionId)).toBe(true);
    expect(canRestoreRevision(confirmed, revision.revisionId)).toBe(false);
    expect(canRestoreRevision(confirmed, 'missing')).toBe(false);
  });
});

describe('selectGuidedStep', () => {
  it('always allows inspection and only updates activeStep', () => {
    const start = createGuidedDemoState();
    const next = selectGuidedStep(start, GUIDED_STEP.APPLY);
    expect(next.activeStep).toBe(GUIDED_STEP.APPLY);
    expect(next.choices).toEqual(start.choices);
    expect(next.draftText).toBe(start.draftText);
    expect(next.appliedAltText).toBe(start.appliedAltText);
    expect(next.outcome).toBe(GUIDED_OUTCOME.NOT_FINISHED);
    expect(namesDecided(next)).toBe(false);
    expect(next.actionHistory).toEqual([]);
  });

  it('does not mark unperformed decisions as complete', () => {
    const next = selectGuidedStep(createGuidedDemoState(), GUIDED_STEP.APPLY);
    expect(next.outcome).toBe(GUIDED_OUTCOME.NOT_FINISHED);
    expect(next.draftStatus).toBe(GUIDED_DRAFT_STATUS.BLOCKED);
  });

  it('returns the same reference when the step is already selected', () => {
    const start = createGuidedDemoState();
    expect(selectGuidedStep(start, GUIDED_STEP.CONTEXT)).toBe(start);
  });
});

describe('chooseGuidedName', () => {
  it('returns the same reference when the requested choice is unchanged', () => {
    const scenario = createGuidedScenario();
    const left = chooseGuidedName(createGuidedDemoState(), scenario, 'left', INCLUDE);
    expect(chooseGuidedName(left, scenario, 'left', INCLUDE)).toBe(left);
  });

  it('returns the same reference while a pending choice change is open', () => {
    const scenario = createGuidedScenario();
    const pending = chooseGuidedName(
      editGuidedDraft(includeBoth(scenario), 'Do not clobber me.'),
      scenario,
      'left',
      OMIT,
    );
    expect(chooseGuidedName(pending, scenario, 'right', OMIT)).toBe(pending);
  });

  it('keeps the candidate blocked until both faces have a choice', () => {
    const scenario = createGuidedScenario();
    const leftOnly = chooseGuidedName(createGuidedDemoState(), scenario, 'left', INCLUDE);
    expect(leftOnly.draftStatus).toBe(GUIDED_DRAFT_STATUS.BLOCKED);
    expect(leftOnly.draftText).toBeNull();
    expect(leftOnly.draftVersion).toBe(0);
    expect(canPreview(leftOnly)).toBe(false);
    expect(canApply(leftOnly)).toBe(false);
  });

  it('loads the matching recorded sample, increments draftVersion, and clears preview when names are decided', () => {
    const scenario = createGuidedScenario();
    const previewed = previewGuidedDraft(includeBoth(scenario));
    const changed = chooseGuidedName(previewed, scenario, 'right', OMIT);
    expect(changed.draftText).toBe(scenario.samples[TRIBECA]['justin-trudeau']);
    expect(changed.draftOrigin).toBe(GUIDED_DRAFT_ORIGIN.RECORDED_SAMPLE);
    expect(changed.draftVersion).toBe(previewed.draftVersion + 1);
    expect(changed.previewedVersion).toBeNull();
    expect(changed.outcome).toBe(GUIDED_OUTCOME.NOT_FINISHED);
    expect(changed.appliedAltText).toBe(previewed.appliedAltText);
  });

  it('uses the selected image sample and reports absent variants as fixture_missing', () => {
    const scenario = createGuidedScenario();
    const coachellaBoth = chooseBoth(createGuidedDemoState(), scenario, INCLUDE, INCLUDE, COACHELLA);
    expect(coachellaBoth.draftStatus).toBe(GUIDED_DRAFT_STATUS.READY);
    expect(coachellaBoth.draftText).toBe(scenario.samples[COACHELLA].both);

    const coachellaPartial = chooseBoth(createGuidedDemoState(), scenario, INCLUDE, OMIT, COACHELLA);
    expect(coachellaPartial.draftStatus).toBe(GUIDED_DRAFT_STATUS.FIXTURE_MISSING);
    expect(coachellaPartial.draftText).toBeNull();
  });

  it('covers every include/omit combination and every one-undecided state (T03)', () => {
    const scenario = createGuidedScenario();
    const start = createGuidedDemoState();
    const cases: Array<{
      left: GuidedNameChoice;
      right: GuidedNameChoice;
      key: GuidedSampleKey | null;
    }> = [
      { left: UNDECIDED, right: UNDECIDED, key: null },
      { left: INCLUDE, right: UNDECIDED, key: null },
      { left: OMIT, right: UNDECIDED, key: null },
      { left: UNDECIDED, right: INCLUDE, key: null },
      { left: UNDECIDED, right: OMIT, key: null },
      { left: INCLUDE, right: INCLUDE, key: 'both' },
      { left: INCLUDE, right: OMIT, key: 'justin-trudeau' },
      { left: OMIT, right: INCLUDE, key: 'katy-perry' },
      { left: OMIT, right: OMIT, key: 'none' },
    ];

    for (const { left, right, key } of cases) {
      let state = start;
      if (left !== UNDECIDED) {
        state = chooseGuidedName(state, scenario, 'left', left);
      }
      if (right !== UNDECIDED) {
        state = chooseGuidedName(state, scenario, 'right', right);
      }
      expect(guidedDraftKeyFor(state.choices)).toBe(key);
      if (key === null) {
        expect(state.draftStatus).toBe(GUIDED_DRAFT_STATUS.BLOCKED);
        expect(state.draftText).toBeNull();
        expect(canPreview(state)).toBe(false);
        expect(canApply(state)).toBe(false);
      } else {
        expect(state.draftStatus).toBe(GUIDED_DRAFT_STATUS.READY);
        expect(state.draftText).toBe(scenario.samples[TRIBECA][key]);
        expect(state.draftOrigin).toBe(GUIDED_DRAFT_ORIGIN.RECORDED_SAMPLE);
      }
    }
  });

  it('does not overwrite a visitor edit; it stores pendingChoiceChange instead (T07)', () => {
    const scenario = createGuidedScenario();
    const edited = editGuidedDraft(includeBoth(scenario), 'A distinctive manually edited draft.');
    const pending = chooseGuidedName(edited, scenario, 'right', OMIT);
    expect(pending.pendingChoiceChange).toEqual({ position: 'right', choice: OMIT });
    expect(pending.choices).toEqual(edited.choices);
    expect(pending.draftText).toBe('A distinctive manually edited draft.');
    expect(pending.draftOrigin).toBe(GUIDED_DRAFT_ORIGIN.VISITOR_EDIT);
    expect(pending.appliedAltText).toBe(edited.appliedAltText);
  });

  it('records a local action summary from guided copy, not hand-written prose', () => {
    const scenario = createGuidedScenario();
    const left = chooseGuidedName(createGuidedDemoState(), scenario, 'left', INCLUDE);
    expect(left.actionHistory).toHaveLength(1);
    expect(left.actionHistory[0]?.scope).toBe('local');
    expect(left.actionHistory[0]?.summary).toBe(guidedCopy('names.included', { name: 'Justin Trudeau' }));
  });
});

describe('confirmGuidedChoiceReplacement and cancelGuidedChoiceReplacement', () => {
  it('confirm returns the same reference when nothing is pending', () => {
    const scenario = createGuidedScenario();
    const state = includeBoth(scenario);
    expect(confirmGuidedChoiceReplacement(state, scenario)).toBe(state);
  });

  it('cancel returns the same reference when nothing is pending', () => {
    const state = createGuidedDemoState();
    expect(cancelGuidedChoiceReplacement(state)).toBe(state);
  });

  it('cancel keeps choices, draft text, version and applied text (T07)', () => {
    const scenario = createGuidedScenario();
    const edited = editGuidedDraft(includeBoth(scenario), 'A distinctive manually edited draft.');
    const pending = chooseGuidedName(edited, scenario, 'right', OMIT);
    const cancelled = cancelGuidedChoiceReplacement(pending);
    expect(cancelled.pendingChoiceChange).toBeNull();
    expect(cancelled.choices).toEqual(edited.choices);
    expect(cancelled.draftText).toBe(edited.draftText);
    expect(cancelled.draftVersion).toBe(edited.draftVersion);
    expect(cancelled.appliedAltText).toBe(edited.appliedAltText);
    expect(cancelled.actionHistory.at(-1)?.summary).toBe(guidedCopy('names.change_cancel'));
  });

  it('does not treat opening or cancelling a name-change dialog as finishing an apply (T07)', () => {
    const scenario = createGuidedScenario();
    const applied = applyGuidedDraft(
      previewGuidedDraft(editGuidedDraft(includeBoth(scenario), 'A distinctive manually edited draft.')),
    );
    expect(applied.outcome).toBe(GUIDED_OUTCOME.APPLIED);

    const pending = chooseGuidedName(applied, scenario, 'right', OMIT);
    expect(pending.pendingChoiceChange).toEqual({ position: 'right', choice: OMIT });
    expect(pending.outcome).toBe(GUIDED_OUTCOME.APPLIED);
    expect(pending.actionHistory).toEqual(applied.actionHistory);

    const cancelled = cancelGuidedChoiceReplacement(pending);
    expect(cancelled.pendingChoiceChange).toBeNull();
    expect(cancelled.outcome).toBe(GUIDED_OUTCOME.APPLIED);
    expect(cancelled.appliedAltText).toBe(applied.appliedAltText);
    expect(cancelled.choices).toEqual(applied.choices);
    expect(cancelled.draftText).toBe(applied.draftText);

    const kept = keepGuidedCurrentAltText(applied);
    const pendingKept = chooseGuidedName(kept, scenario, 'right', OMIT);
    expect(pendingKept.outcome).toBe(GUIDED_OUTCOME.KEPT);
    expect(cancelGuidedChoiceReplacement(pendingKept).outcome).toBe(GUIDED_OUTCOME.KEPT);
  });

  it('confirm archives the current draft, loads the matching sample, and never relabels the edit as recorded (T07)', () => {
    const scenario = createGuidedScenario();
    const edited = editGuidedDraft(includeBoth(scenario), 'A distinctive manually edited draft.');
    const appliedBefore = edited.appliedAltText;
    const undoBefore = edited.applicationUndoStack;
    const confirmed = confirmGuidedChoiceReplacement(chooseGuidedName(edited, scenario, 'right', OMIT), scenario);
    expect(confirmed.pendingChoiceChange).toBeNull();
    expect(confirmed.choices).toEqual({ left: INCLUDE, right: OMIT });
    expect(confirmed.draftText).toBe(scenario.samples[TRIBECA]['justin-trudeau']);
    expect(confirmed.draftOrigin).toBe(GUIDED_DRAFT_ORIGIN.RECORDED_SAMPLE);
    expect(confirmed.draftVersion).toBe(edited.draftVersion + 1);
    expect(confirmed.previewedVersion).toBeNull();
    expect(confirmed.outcome).toBe(GUIDED_OUTCOME.NOT_FINISHED);
    expect(confirmed.appliedAltText).toBe(appliedBefore);
    expect(confirmed.applicationUndoStack).toEqual(undoBefore);
    expect(confirmed.draftHistory).toEqual([
      expect.objectContaining({
        text: 'A distinctive manually edited draft.',
        origin: GUIDED_DRAFT_ORIGIN.VISITOR_EDIT,
        choices: { left: INCLUDE, right: INCLUDE },
        draftVersion: edited.draftVersion,
      }),
    ]);
  });
});

describe('editGuidedDraft', () => {
  it('returns the same reference when names are not decided', () => {
    const start = createGuidedDemoState();
    expect(editGuidedDraft(start, 'Not yet.')).toBe(start);
  });

  it('returns the same reference when the sample is missing', () => {
    const scenario = withMissingSample(createGuidedScenario(), TRIBECA, 'both');
    const missing = chooseBoth(createGuidedDemoState(), scenario, INCLUDE, INCLUDE);
    expect(editGuidedDraft(missing, 'Cannot edit a missing sample.')).toBe(missing);
  });

  it('stores the textarea value verbatim, marks visitor_edit, and invalidates preview', () => {
    const scenario = createGuidedScenario();
    const previewed = previewGuidedDraft(includeBoth(scenario));
    const padded = '  Distinctive test sentence.  ';
    const edited = editGuidedDraft(previewed, padded);
    expect(edited.draftText).toBe(padded);
    expect(edited.draftOrigin).toBe(GUIDED_DRAFT_ORIGIN.VISITOR_EDIT);
    expect(edited.draftVersion).toBe(previewed.draftVersion + 1);
    expect(edited.previewedVersion).toBeNull();
    expect(edited.outcome).toBe(GUIDED_OUTCOME.NOT_FINISHED);
    expect(edited).not.toHaveProperty('savedDraft');
  });

  it('does not filter names, truncate, or require an identity allowlist', () => {
    const scenario = createGuidedScenario();
    const omitted = chooseBoth(createGuidedDemoState(), scenario, OMIT, OMIT);
    const edited = editGuidedDraft(omitted, 'Katy Perry with Justin Trudeau and extra unused words.');
    expect(edited.draftText).toBe('Katy Perry with Justin Trudeau and extra unused words.');
  });
});

describe('previewGuidedDraft', () => {
  it('returns the same reference when canPreview is false', () => {
    const start = createGuidedDemoState();
    expect(previewGuidedDraft(start)).toBe(start);
    const whitespace = editGuidedDraft(includeBoth(createGuidedScenario()), '   ');
    expect(previewGuidedDraft(whitespace)).toBe(whitespace);
  });

  it('sets previewedVersion to draftVersion, moves to apply, and does not rewrite text', () => {
    const scenario = createGuidedScenario();
    const ready = includeBoth(scenario);
    const previewed = previewGuidedDraft(ready);
    expect(previewed.previewedVersion).toBe(ready.draftVersion);
    expect(previewed.activeStep).toBe(GUIDED_STEP.APPLY);
    expect(previewed.draftText).toBe(ready.draftText);
  });
});

describe('applyGuidedDraft', () => {
  it('returns the same reference when canApply is false, including a stale preview (T08)', () => {
    const scenario = createGuidedScenario();
    const ready = includeBoth(scenario);
    expect(applyGuidedDraft(ready)).toBe(ready);
    const previewed = previewGuidedDraft(ready);
    const stale = editGuidedDraft(previewed, 'Changed after preview.');
    expect(applyGuidedDraft(stale)).toBe(stale);
    expect(stale.appliedAltText).toBe(ORIGINAL_ALT);
    const fresh = previewGuidedDraft(stale);
    expect(applyGuidedDraft(fresh).appliedAltText).toBe('Changed after preview.');
  });

  it('rejects apply after a dependent name change even if the handler is invoked directly (T08)', () => {
    const scenario = createGuidedScenario();
    const stale = chooseGuidedName(previewGuidedDraft(includeBoth(scenario)), scenario, 'right', OMIT);
    expect(applyGuidedDraft(stale)).toBe(stale);
    expect(stale.appliedAltText).toBe(ORIGINAL_ALT);
  });

  it('copies the visible draft byte-for-byte, including surrounding spaces (T05)', () => {
    const scenario = createGuidedScenario();
    const distinctive = '  Distinctive test sentence.  ';
    const applied = applyGuidedDraft(previewGuidedDraft(editGuidedDraft(includeBoth(scenario), distinctive)));
    expect(applied.appliedAltText).toBe(distinctive);
    expect(applied.outcome).toBe(GUIDED_OUTCOME.APPLIED);
    expect(applied.applicationUndoStack[0]?.previousAltText).toBe(ORIGINAL_ALT);
    expect(applied.actionHistory.at(-1)?.summary).toBe(guidedCopy('apply.success'));
  });

  it('refuses a no-change apply of text that is already on the demo copy (T06)', () => {
    const scenario = createGuidedScenario();
    const applied = applyGuidedDraft(previewGuidedDraft(includeBoth(scenario)));
    expect(canApply(applied)).toBe(false);
    expect(applyGuidedDraft(applied)).toBe(applied);
  });
});

describe('undoGuidedApplication', () => {
  it('returns the same reference when the stack is empty', () => {
    const start = createGuidedDemoState();
    expect(undoGuidedApplication(start)).toBe(start);
  });

  it('restores previousAltText in LIFO order and keeps the current draft (T06)', () => {
    const scenario = createGuidedScenario();
    const first = applyGuidedDraft(previewGuidedDraft(includeBoth(scenario)));
    const second = applyGuidedDraft(previewGuidedDraft(editGuidedDraft(first, 'Draft B unique.')));
    expect(second.appliedAltText).toBe('Draft B unique.');
    const undoOnce = undoGuidedApplication(second);
    expect(undoOnce.appliedAltText).toBe(first.appliedAltText);
    expect(undoOnce.draftText).toBe('Draft B unique.');
    expect(undoOnce.choices).toEqual(second.choices);
    const undoTwice = undoGuidedApplication(undoOnce);
    expect(undoTwice.appliedAltText).toBe(ORIGINAL_ALT);
    expect(canUndo(undoTwice)).toBe(false);
    expect(undoGuidedApplication(undoTwice)).toBe(undoTwice);
  });

  it('clears the applied outcome when undo restores the original alt text', () => {
    const scenario = createGuidedScenario();
    const applied = applyGuidedDraft(previewGuidedDraft(includeBoth(scenario)));
    expect(applied.outcome).toBe(GUIDED_OUTCOME.APPLIED);

    const undone = undoGuidedApplication(applied);
    expect(undone.appliedAltText).toBe(ORIGINAL_ALT);
    expect(undone.outcome).toBe(GUIDED_OUTCOME.NOT_FINISHED);
  });

  it('keeps outcome applied when an earlier application remains on the stack', () => {
    const scenario = createGuidedScenario();
    const first = applyGuidedDraft(previewGuidedDraft(includeBoth(scenario)));
    const second = applyGuidedDraft(previewGuidedDraft(editGuidedDraft(first, 'Draft B unique.')));

    const undoOnce = undoGuidedApplication(second);
    expect(undoOnce.appliedAltText).toBe(first.appliedAltText);
    expect(undoOnce.outcome).toBe(GUIDED_OUTCOME.APPLIED);
  });

  it('does not mutate the evidence photograph alternative on the fixture', () => {
    const scenario = createGuidedScenario();
    const applied = applyGuidedDraft(previewGuidedDraft(includeBoth(scenario)));
    undoGuidedApplication(applied);
    expect(scenario.pressPhoto.altText).toBe(ORIGINAL_ALT);
  });
});

describe('keepGuidedCurrentAltText', () => {
  it('is allowed while names are blocked and leaves applied text and draft unchanged', () => {
    const start = createGuidedDemoState();
    const kept = keepGuidedCurrentAltText(start);
    expect(kept.outcome).toBe(GUIDED_OUTCOME.KEPT);
    expect(kept.appliedAltText).toBe(ORIGINAL_ALT);
    expect(kept.draftText).toBeNull();
    expect(kept.actionHistory.at(-1)?.summary).toBe(guidedCopy('outcome.kept'));
  });

  it('remains available when the matching sample is missing (T04)', () => {
    const scenario = withMissingSample(createGuidedScenario(), TRIBECA, 'justin-trudeau');
    const missing = chooseBoth(createGuidedDemoState(), scenario, INCLUDE, OMIT);
    const kept = keepGuidedCurrentAltText(missing);
    expect(kept.outcome).toBe(GUIDED_OUTCOME.KEPT);
    expect(kept.appliedAltText).toBe(ORIGINAL_ALT);
    expect(kept.choices).toEqual(missing.choices);
    expect(kept.draftStatus).toBe(GUIDED_DRAFT_STATUS.FIXTURE_MISSING);
  });

  it('restores the original alt when keep is chosen after apply so kept means unchanged', () => {
    const scenario = createGuidedScenario();
    const applied = applyGuidedDraft(previewGuidedDraft(includeBoth(scenario)));
    expect(applied.appliedAltText).not.toBe(ORIGINAL_ALT);

    const kept = keepGuidedCurrentAltText(applied);
    expect(kept.outcome).toBe(GUIDED_OUTCOME.KEPT);
    expect(kept.appliedAltText).toBe(ORIGINAL_ALT);
    expect(canUndo(kept)).toBe(false);
  });
});

describe('restoreGuidedRevision', () => {
  const archivedMismatch = () => {
    const scenario = createGuidedScenario();
    const first = editGuidedDraft(includeBoth(scenario), 'First manual draft.');
    const confirmed = confirmGuidedChoiceReplacement(chooseGuidedName(first, scenario, 'right', OMIT), scenario);
    const second = editGuidedDraft(confirmed, 'Second manual draft.');
    return { scenario, first, confirmed, second, revision: confirmed.draftHistory[0] };
  };

  it('returns the same reference when the revision is missing', () => {
    const state = createGuidedDemoState();
    expect(restoreGuidedRevision(state, 'rev-missing', 'full')).toBe(state);
    expect(restoreGuidedRevision(state, 'rev-missing', 'copy_only')).toBe(state);
  });

  it('blocks a mismatched full restore and allows copy-only recovery (T13)', () => {
    const { confirmed, revision } = archivedMismatch();
    expect(revision).toBeDefined();
    expect(restoreGuidedRevision(confirmed, revision.revisionId, 'full')).toBe(confirmed);
    const copied = restoreGuidedRevision(confirmed, revision.revisionId, 'copy_only');
    expect(copied).not.toBe(confirmed);
    expect(copied.draftText).toBe('First manual draft.');
    expect(copied.draftOrigin).toBe(GUIDED_DRAFT_ORIGIN.VISITOR_EDIT);
    expect(copied.choices).toEqual(confirmed.choices);
    expect(copied.previewedVersion).toBeNull();
    expect(copied.appliedAltText).toBe(confirmed.appliedAltText);
    expect(copied.outcome).toBe(GUIDED_OUTCOME.NOT_FINISHED);
  });

  it('restores a matching revision as visitor_edit, archives the current manual draft, and does not apply (T13)', () => {
    const { scenario, confirmed, revision } = archivedMismatch();
    expect(revision).toBeDefined();
    const matching = editGuidedDraft(chooseGuidedName(confirmed, scenario, 'right', INCLUDE), 'Current manual draft.');
    const restored = restoreGuidedRevision(matching, revision.revisionId, 'full');
    expect(restored.draftText).toBe('First manual draft.');
    expect(restored.draftOrigin).toBe(GUIDED_DRAFT_ORIGIN.VISITOR_EDIT);
    expect(restored.choices).toEqual({ left: INCLUDE, right: INCLUDE });
    expect(restored.draftVersion).toBe(matching.draftVersion + 1);
    expect(restored.previewedVersion).toBeNull();
    expect(restored.appliedAltText).toBe(matching.appliedAltText);
    expect(restored.outcome).toBe(GUIDED_OUTCOME.NOT_FINISHED);
    expect(restored.draftHistory.map((entry) => entry.text)).toContain('Current manual draft.');
    expect(canApply(restored)).toBe(false);
  });
});

describe('resetGuidedDemoState', () => {
  it('restores core initial values and empty local histories (T17)', () => {
    const scenario = createGuidedScenario();
    const used = applyGuidedDraft(previewGuidedDraft(editGuidedDraft(includeBoth(scenario), 'Used draft.')));
    const before = snapshot(used);
    const fresh = resetGuidedDemoState(used);
    expect(fresh).toEqual(createGuidedDemoState());
    expect(fresh).not.toBe(used);
    expect(snapshot(used)).toBe(before);
  });
});

describe('retryGuidedFixture', () => {
  it('marks a missing sample as fixture_missing without inventing text or changing applied alt (T04)', () => {
    const scenario = withMissingSample(createGuidedScenario(), TRIBECA, 'justin-trudeau');
    const missing = chooseBoth(createGuidedDemoState(), scenario, INCLUDE, OMIT);
    expect(missing.draftStatus).toBe(GUIDED_DRAFT_STATUS.FIXTURE_MISSING);
    expect(missing.draftText).toBeNull();
    expect(missing.draftOrigin).toBe(GUIDED_DRAFT_ORIGIN.NONE);
    expect(missing.choices).toEqual({ left: INCLUDE, right: OMIT });
    expect(missing.appliedAltText).toBe(ORIGINAL_ALT);
    expect(canPreview(missing)).toBe(false);
    expect(canApply(missing)).toBe(false);
    expect(previewGuidedDraft(missing)).toBe(missing);
    expect(applyGuidedDraft(missing)).toBe(missing);
  });

  it('returns the same reference when the status is not fixture_missing or the sample is still absent', () => {
    const scenario = createGuidedScenario();
    const ready = includeBoth(scenario);
    expect(retryGuidedFixture(ready, scenario)).toBe(ready);
    const missingScenario = withMissingSample(scenario, TRIBECA, 'both');
    const missing = chooseBoth(createGuidedDemoState(), missingScenario, INCLUDE, INCLUDE);
    expect(retryGuidedFixture(missing, missingScenario)).toBe(missing);
  });

  it('loads the recorded sample when a retry finds it', () => {
    const missingScenario = withMissingSample(createGuidedScenario(), TRIBECA, 'both');
    const missing = chooseBoth(createGuidedDemoState(), missingScenario, INCLUDE, INCLUDE);
    const recovered = retryGuidedFixture(missing, createGuidedScenario());
    expect(recovered.draftStatus).toBe(GUIDED_DRAFT_STATUS.READY);
    expect(recovered.draftOrigin).toBe(GUIDED_DRAFT_ORIGIN.RECORDED_SAMPLE);
    expect(recovered.draftText).toBe(createGuidedScenario().samples[TRIBECA].both);
    expect(recovered.draftVersion).toBe(missing.draftVersion + 1);
    expect(recovered.previewedVersion).toBeNull();
  });

  it('retries against the selected image sample set', () => {
    const missingScenario = withMissingSample(createGuidedScenario(), COACHELLA, 'both');
    const missing = chooseBoth(createGuidedDemoState(), missingScenario, INCLUDE, INCLUDE, COACHELLA);
    const recovered = retryGuidedFixture(missing, createGuidedScenario(), COACHELLA);
    expect(recovered.draftStatus).toBe(GUIDED_DRAFT_STATUS.READY);
    expect(recovered.draftText).toBe(createGuidedScenario().samples[COACHELLA].both);
  });
});

describe('immutability', () => {
  it('never mutates the input state on a successful or refused transition', () => {
    const scenario = createGuidedScenario();
    const start = createGuidedDemoState();
    const before = snapshot(start);
    selectGuidedStep(start, GUIDED_STEP.NAMES);
    chooseGuidedName(start, scenario, 'left', INCLUDE);
    expect(snapshot(start)).toBe(before);

    const ready = includeBoth(scenario);
    const readyBefore = snapshot(ready);
    const edited = editGuidedDraft(ready, 'New text.');
    expect(snapshot(ready)).toBe(readyBefore);
    expect(edited).not.toBe(ready);
    expect(editGuidedDraft(start, 'nope')).toBe(start);
  });
});

describe('network boundary (T01, T18)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('has no fetch, XHR, window, storage, timer, or ../api import surface in the module source', () => {
    const source = readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'state.ts'), 'utf8');
    expect(source).not.toMatch(/\bfetch\s*\(/);
    expect(source).not.toMatch(/\bXMLHttpRequest\b/);
    expect(source).not.toMatch(/from ['"]\.\.\/api\//);
    expect(source).not.toMatch(/\bwindow\b/);
    expect(source).not.toMatch(/\blocalStorage\b/);
    expect(source).not.toMatch(/\bsessionStorage\b/);
    expect(source).not.toMatch(/\bsetTimeout\b/);
    expect(source).not.toMatch(/\bsetInterval\b/);
  });

  it('completes a recorded walkthrough with zero fetch calls', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const scenario = createGuidedScenario();
    let state = includeBoth(scenario);
    state = editGuidedDraft(state, 'Custom walkthrough alt text.');
    state = previewGuidedDraft(state);
    state = applyGuidedDraft(state);
    state = undoGuidedApplication(state);
    state = keepGuidedCurrentAltText(state);
    state = resetGuidedDemoState(state);
    expect(state.appliedAltText).toBe(ORIGINAL_ALT);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
