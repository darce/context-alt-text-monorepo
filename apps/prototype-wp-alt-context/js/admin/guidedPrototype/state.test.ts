import { describe, expect, it } from 'vitest';

import {
  applyGuidedCandidate,
  confirmGuidedIdentity,
  createGuidedScenario,
  leaveGuidedIdentityUnidentified,
  rejectGuidedCandidate,
  saveGuidedEdit,
  undoGuidedApplication,
} from './state';

describe('guided prototype scenario state', () => {
  it('starts from an illustrative saved scenario without changing the original media', () => {
    const scenario = createGuidedScenario();

    expect(scenario.origin).toBe('illustrative');
    expect(scenario.scenarioVersion).toBe('guided-portrait-v1');
    expect(scenario.identity.status).toBe('unconfirmed');
    expect(scenario.candidate.text).toContain('person');
    expect(scenario.appliedText).toBe('Portrait of a person in a grey jacket.');
    expect(scenario.originalMedia.altText).toBe(scenario.appliedText);
    expect(scenario.history).toEqual([]);
  });

  it('weaves a confirmed identity into the candidate while leaving applied text alone', () => {
    const initial = createGuidedScenario();

    const confirmed = confirmGuidedIdentity(initial);

    expect(confirmed.identity).toEqual({
      status: 'confirmed',
      name: 'Keanu Reeves',
      source: 'sample-record',
    });
    expect(confirmed.candidate.text).toContain('Keanu Reeves');
    expect(confirmed.appliedText).toBe(initial.appliedText);
    expect(confirmed.history.at(-1)).toMatchObject({ kind: 'identity-confirmed' });
  });

  it('keeps the unresolved route useful and prevents a name from leaking into the draft', () => {
    const initial = createGuidedScenario();

    const unresolved = leaveGuidedIdentityUnidentified(initial);

    expect(unresolved.identity).toEqual({ status: 'unidentified', source: 'none' });
    expect(unresolved.candidate.text).toBe('Portrait of a person in a grey jacket.');
    expect(unresolved.candidate.text).not.toContain('Keanu Reeves');
    expect(unresolved.appliedText).toBe(initial.appliedText);
  });

  it('keeps editing and rejection separate from explicit application, then supports undo', () => {
    const confirmed = confirmGuidedIdentity(createGuidedScenario());
    const edited = saveGuidedEdit(confirmed, 'Keanu Reeves wears a grey jacket against a plain background.');
    const rejected = rejectGuidedCandidate(edited);

    expect(rejected.candidate.status).toBe('rejected');
    expect(rejected.appliedText).toBe(confirmed.appliedText);
    expect(() => applyGuidedCandidate(rejected)).toThrow('rejected');

    const readyToApply = saveGuidedEdit(confirmed, 'Keanu Reeves wears a grey jacket against a plain background.');
    const applied = applyGuidedCandidate(readyToApply);

    expect(applied.appliedText).toBe(readyToApply.candidate.text);
    expect(applied.history.at(-1)).toMatchObject({ kind: 'applied' });

    const undone = undoGuidedApplication(applied);
    expect(undone.appliedText).toBe(confirmed.appliedText);
    expect(undone.history.at(-1)).toMatchObject({ kind: 'application-undone' });
  });
});
