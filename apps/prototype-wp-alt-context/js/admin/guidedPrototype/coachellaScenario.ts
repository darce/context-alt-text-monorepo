import guidedCoachellaPhoto from '../assets/guided/guided-press-coachella-2026.webp';

import {
  createGuidedScenario,
  type GuidedDraftKey,
  type GuidedFaceBox,
  type GuidedLabeledPerson,
  type GuidedScenario,
} from './state';

/** The source fixture supplied for the second scenario; it is not a live upload. */
export const COACHELLA_SOURCE_FIXTURE =
  'docs/assessments/current/demo/v2/katy-perry-and-justin-trudeau-at-coachella-v0-z697qk161rug1.webp';

export const COACHELLA_SCENARIO_VERSION = 'guided-coachella-v1';

export const COACHELLA_IMAGE_DIMENSIONS = {
  width: 640,
  height: 852,
} as const;

/** Approximate crops checked against the supplied 640 × 852 fixture, not detector output. */
export const COACHELLA_FACE_BOXES: Record<'left' | 'right', GuidedFaceBox> = {
  left: { x: 190, y: 150, width: 115, height: 160 },
  right: { x: 370, y: 175, width: 115, height: 150 },
};

export const COACHELLA_IDENTITIES = {
  left: 'Justin Trudeau',
  right: 'Katy Perry',
} as const;

export const COACHELLA_DRAFT_KEYS: readonly GuidedDraftKey[] = ['none', 'justin-trudeau', 'katy-perry', 'both'];

const clonePeople = (people: GuidedLabeledPerson[]): GuidedLabeledPerson[] =>
  people.map((person) => ({
    ...person,
    galleryPhotos: person.galleryPhotos.map((photo) => ({ ...photo })),
  }));

const cloneCoachellaScenario = (scenario: GuidedScenario): GuidedScenario => ({
  ...scenario,
  pressPhoto: { ...scenario.pressPhoto },
  pageContext: { ...scenario.pageContext },
  people: clonePeople(scenario.people),
  faces: scenario.faces.map((face) => ({ ...face, box: { ...face.box } })),
  visualFacts: [...scenario.visualFacts],
  samples: { ...scenario.samples },
  provenance: { ...scenario.provenance },
  ...(scenario.identitySource
    ? {
        identitySource: {
          ...scenario.identitySource,
          names: { ...scenario.identitySource.names },
        },
      }
    : {}),
});

const roster = createGuidedScenario();

/**
 * Prepared fixture for a later recorded walkthrough. The four samples stay null
 * until the operator returns four real GPU adapter outputs; null is deliberate,
 * not placeholder copy.
 */
export const COACHELLA_SCENARIO: GuidedScenario = {
  origin: 'user-supplied',
  scenarioVersion: COACHELLA_SCENARIO_VERSION,
  pressPhoto: {
    src: guidedCoachellaPhoto,
    altText: 'User-supplied festival photo; source caption unavailable.',
    credit: 'Source and original credit unavailable; fixture supplied by the user.',
    event: 'Coachella attribution from the supplied fixture filename; event, date and location not independently verified.',
    source: COACHELLA_SOURCE_FIXTURE,
  },
  pageContext: {
    title: 'User-supplied festival photo (event not independently verified)',
    summary: 'This image was supplied for the second scenario. Its original caption, date, location and credit are unavailable.',
    runDate: 'not recorded',
  },
  // Reuse the existing reference roster; this scenario adds a different supplied
  // photo without changing the incumbent Tribeca fixture or its values.
  people: clonePeople(roster.people),
  faces: [
    {
      id: 'justin-trudeau',
      position: 'left',
      box: { ...COACHELLA_FACE_BOXES.left },
      matchedPersonKey: 'justin-trudeau',
      similarity: null,
      strength: null,
      note: 'User-supplied identity label and approximate visual crop; no face-recognition match or score is recorded.',
      source: 'user-supplied',
    },
    {
      id: 'katy-perry',
      position: 'right',
      box: { ...COACHELLA_FACE_BOXES.right },
      matchedPersonKey: 'katy-perry',
      similarity: null,
      strength: null,
      note: 'User-supplied identity label and approximate visual crop; no face-recognition match or score is recorded.',
      source: 'user-supplied',
    },
  ],
  visualFacts: [
    'Two people sit together at a table.',
    'The person on the left wears a light shirt and a backwards cap.',
    'The person on the right has long dark hair and holds a red cup.',
    'A snack packet, cups and plants are visible.',
  ],
  samples: {
    none: null,
    'justin-trudeau': null,
    'katy-perry': null,
    both: null,
  },
  provenance: {
    service: 'Not applicable — no recognition run recorded',
    model: 'Not applicable',
    runDate: 'not recorded',
    threshold: null,
    note: 'The image and identity labels were supplied by the user. This scenario does not claim independent face recognition, match scores or confidence.',
    alsoChecked: 'No source caption, AltText.ai sample, or event/date/location verification is recorded.',
  },
  identitySource: {
    kind: 'user-supplied',
    names: { ...COACHELLA_IDENTITIES },
    source: COACHELLA_SOURCE_FIXTURE,
    note: 'The user supplied these identities and left/right assignments. They are not independently verified face recognition.',
  },
};

export const createCoachellaScenario = (): GuidedScenario => cloneCoachellaScenario(COACHELLA_SCENARIO);
