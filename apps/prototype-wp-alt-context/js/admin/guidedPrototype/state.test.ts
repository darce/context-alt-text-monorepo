import { describe, expect, it } from 'vitest';

import {
  applyGuidedCandidate,
  confirmGuidedIdentity,
  createGuidedScenario,
  getLastGuidedApplication,
  leaveGuidedIdentityUnidentified,
  rejectGuidedCandidate,
  resetGuidedScenario,
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
    expect(scenario.originalMedia.src).toContain('altcontext-sample');
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
    const repeatedUndo = undoGuidedApplication(undone);
    expect(undone.appliedText).toBe(confirmed.appliedText);
    expect(undone.history.at(-1)).toMatchObject({ kind: 'application-undone' });
    expect(repeatedUndo).toEqual(undone);
  });

  it('treats applying the already-applied text as an idempotent action', () => {
    const confirmed = confirmGuidedIdentity(createGuidedScenario());
    const edited = saveGuidedEdit(confirmed, 'Keanu Reeves wears a grey jacket against a plain background.');

    const applied = applyGuidedCandidate(edited);
    const repeated = applyGuidedCandidate(applied);
    const undone = undoGuidedApplication(repeated);

    expect(repeated.history).toEqual(applied.history);
    expect(undone.appliedText).toBe(confirmed.appliedText);
  });

  it('does not allow an unconfirmed route to save or apply the sample identity', () => {
    const unidentified = leaveGuidedIdentityUnidentified(createGuidedScenario());

    expect(() => saveGuidedEdit(unidentified, 'Keanu Reeves is pictured in a grey jacket.')).toThrow(
      'identity is confirmed',
    );
    expect(() =>
      applyGuidedCandidate({
        ...unidentified,
        candidate: { text: 'Keanu Reeves is pictured in a grey jacket.', status: 'edited' },
      }),
    ).toThrow('identity is confirmed');
    expect(unidentified.appliedText).toBe(unidentified.originalMedia.altText);
  });

  it('consumes applications in LIFO order and restores each prior applied value', () => {
    const confirmed = confirmGuidedIdentity(createGuidedScenario());
    const first = applyGuidedCandidate(confirmed);
    const secondDraft = saveGuidedEdit(first, 'Keanu Reeves wears a grey jacket.');
    const second = applyGuidedCandidate(secondDraft);

    const undoSecond = undoGuidedApplication(second);
    const undoFirst = undoGuidedApplication(undoSecond);
    const exhausted = undoGuidedApplication(undoFirst);

    expect(undoSecond.appliedText).toBe(first.appliedText);
    expect(getLastGuidedApplication(undoSecond.history)).toMatchObject({ kind: 'applied', text: first.appliedText });
    expect(undoFirst.appliedText).toBe(confirmed.appliedText);
    expect(getLastGuidedApplication(undoFirst.history)).toBeUndefined();
    expect(undoFirst.history.filter((event) => event.kind === 'application-undone')).toHaveLength(2);
    expect(exhausted).toEqual(undoFirst);
  });

  it('clones the illustrative seed so practice instances stay isolated', () => {
    const first = createGuidedScenario();
    first.visualFacts.push('Mutated during practice');
    first.originalMedia.altText = 'Mutated during practice';
    first.sourceRecord.name = 'Mutated during practice';

    const second = createGuidedScenario();

    expect(second.visualFacts).toEqual(['Portrait crop', 'Grey jacket', 'Plain background']);
    expect(second.originalMedia.altText).toBe('Portrait of a person in a grey jacket.');
    expect(second.sourceRecord.name).toBe('Keanu Reeves');
  });

  it('resets to a fresh memory-only scenario without carrying decisions forward', () => {
    const applied = applyGuidedCandidate(confirmGuidedIdentity(createGuidedScenario()));

    const reset = resetGuidedScenario();

    expect(applied.appliedText).toContain('Keanu Reeves');
    expect(reset).toEqual(createGuidedScenario());
    expect(reset.history).toEqual([]);
    expect(reset.identity).toEqual({ status: 'unconfirmed', source: 'none' });
  });
});
