export type GuidedCandidateStatus = 'ready' | 'edited' | 'rejected';
export type GuidedIdentityStatus = 'unconfirmed' | 'confirmed' | 'unidentified';

export interface GuidedIdentity {
  status: GuidedIdentityStatus;
  name?: string;
  source: 'sample-record' | 'none';
}

export interface GuidedHistoryEvent {
  kind: 'identity-confirmed' | 'identity-unidentified' | 'edit-saved' | 'rejected' | 'applied' | 'application-undone';
  text?: string;
  previousAppliedText?: string;
}

export interface GuidedScenario {
  origin: 'illustrative' | 'saved-build';
  scenarioVersion: string;
  originalMedia: {
    src: string;
    altText: string;
  };
  sourceRecord: {
    name: string;
    credit: string;
    note: string;
  };
  pageContext: {
    title: string;
    summary: string;
  };
  visualFacts: string[];
  genericDraft: string;
  namedDraft: string;
  unnamedDraft: string;
  identity: GuidedIdentity;
  candidate: {
    text: string;
    status: GuidedCandidateStatus;
  };
  appliedText: string;
  history: GuidedHistoryEvent[];
}

const GUIDED_SCENARIO_SEED: Omit<GuidedScenario, 'identity' | 'candidate' | 'appliedText' | 'history'> = {
  origin: 'illustrative',
  scenarioVersion: 'guided-portrait-v1',
  originalMedia: {
    src: '/wp-content/uploads/2026/09/guided-portrait.jpg',
    altText: 'Portrait of a person in a grey jacket.',
  },
  sourceRecord: {
    name: 'Keanu Reeves',
    credit: 'Governo do Estado de São Paulo',
    note: 'Sample record metadata is evidence for practice. It is not facial identification by the tour.',
  },
  pageContext: {
    title: 'Illustrative actor profile',
    summary: 'A portrait used in an actor profile where a confirmed name helps the description make sense.',
  },
  visualFacts: ['Portrait crop', 'Grey jacket', 'Plain background'],
  genericDraft: 'Portrait of a person in a grey jacket.',
  namedDraft: 'Keanu Reeves wears a grey jacket against a plain background.',
  unnamedDraft: 'Portrait of a person in a grey jacket.',
};

const cloneScenario = (scenario: GuidedScenario): GuidedScenario => ({
  ...scenario,
  originalMedia: { ...scenario.originalMedia },
  sourceRecord: { ...scenario.sourceRecord },
  pageContext: { ...scenario.pageContext },
  visualFacts: [...scenario.visualFacts],
  identity: { ...scenario.identity },
  candidate: { ...scenario.candidate },
  history: scenario.history.map((event) => ({ ...event })),
});

const withHistory = (scenario: GuidedScenario, event: GuidedHistoryEvent): GuidedScenario => ({
  ...cloneScenario(scenario),
  history: [...scenario.history.map((item) => ({ ...item })), event],
});

export const createGuidedScenario = (): GuidedScenario => ({
  ...GUIDED_SCENARIO_SEED,
  identity: { status: 'unconfirmed', source: 'none' },
  candidate: { text: GUIDED_SCENARIO_SEED.genericDraft, status: 'ready' },
  appliedText: GUIDED_SCENARIO_SEED.originalMedia.altText,
  history: [],
});

export const confirmGuidedIdentity = (scenario: GuidedScenario): GuidedScenario =>
  withHistory(
    {
      ...cloneScenario(scenario),
      identity: { status: 'confirmed', name: scenario.sourceRecord.name, source: 'sample-record' },
      candidate: { text: scenario.namedDraft, status: 'ready' },
    },
    { kind: 'identity-confirmed' },
  );

export const leaveGuidedIdentityUnidentified = (scenario: GuidedScenario): GuidedScenario =>
  withHistory(
    {
      ...cloneScenario(scenario),
      identity: { status: 'unidentified', source: 'none' },
      candidate: { text: scenario.unnamedDraft, status: 'ready' },
    },
    { kind: 'identity-unidentified' },
  );

export const saveGuidedEdit = (scenario: GuidedScenario, text: string): GuidedScenario => {
  const trimmedText = text.trim();
  if (trimmedText === '') {
    throw new Error('A description cannot be empty.');
  }

  return withHistory(
    {
      ...cloneScenario(scenario),
      candidate: { text: trimmedText, status: 'edited' },
    },
    { kind: 'edit-saved', text: trimmedText },
  );
};

export const rejectGuidedCandidate = (scenario: GuidedScenario): GuidedScenario =>
  withHistory(
    {
      ...cloneScenario(scenario),
      candidate: { ...scenario.candidate, status: 'rejected' },
    },
    { kind: 'rejected', text: scenario.candidate.text },
  );

export const applyGuidedCandidate = (scenario: GuidedScenario): GuidedScenario => {
  if (scenario.candidate.status === 'rejected') {
    throw new Error('Cannot apply a rejected description.');
  }

  return withHistory(
    { ...cloneScenario(scenario), appliedText: scenario.candidate.text },
    { kind: 'applied', text: scenario.candidate.text, previousAppliedText: scenario.appliedText },
  );
};

export const undoGuidedApplication = (scenario: GuidedScenario): GuidedScenario => {
  const lastApplication = [...scenario.history].reverse().find((event) => event.kind === 'applied');
  if (lastApplication?.previousAppliedText === undefined) {
    return cloneScenario(scenario);
  }

  return withHistory(
    { ...cloneScenario(scenario), appliedText: lastApplication.previousAppliedText },
    { kind: 'application-undone', text: lastApplication.previousAppliedText },
  );
};
