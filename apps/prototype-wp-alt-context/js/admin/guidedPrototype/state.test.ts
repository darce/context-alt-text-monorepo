import { describe, expect, it } from 'vitest';

import {
  applyGuidedCandidate,
  confirmGuidedIdentity,
  confirmedPersonKeys,
  createGuidedScenario,
  draftFor,
  draftKeyFor,
  getGuidedFace,
  getGuidedIdentity,
  getGuidedPerson,
  getLastGuidedApplication,
  GUIDED_CANDIDATE_STATUS,
  GUIDED_IDENTITY_STATUS,
  GUIDED_PERSON_KEYS,
  leaveGuidedIdentityUnidentified,
  nameGuardError,
  rejectGuidedCandidate,
  resetGuidedScenario,
  saveGuidedEdit,
  undoGuidedApplication,
} from './state';

const KATY = 'katy-perry';
const JUSTIN = 'justin-trudeau';

describe('guided prototype scenario state (two people, one press photo)', () => {
  it('starts from a saved run with two labelled people, two matched faces and no decisions yet', () => {
    const scenario = createGuidedScenario();

    expect(scenario.origin).toBe('saved-build');
    expect(scenario.scenarioVersion).toBe('guided-people-v3');
    expect(GUIDED_PERSON_KEYS).toEqual([KATY, JUSTIN]);
    expect(scenario.people.map((person) => person.key)).toEqual([KATY, JUSTIN]);
    expect(scenario.faces.map((face) => [face.id, face.position])).toEqual([
      [JUSTIN, 'left'],
      [KATY, 'right'],
    ]);
    expect(scenario.identities).toEqual([
      { faceId: JUSTIN, status: GUIDED_IDENTITY_STATUS.UNCONFIRMED, source: 'none' },
      { faceId: KATY, status: GUIDED_IDENTITY_STATUS.UNCONFIRMED, source: 'none' },
    ]);

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
      savedPhotoCount: 2,
    });
    expect(getGuidedPerson(scenario, KATY).galleryPhotos.map((photo) => photo.src)).toEqual([
      expect.stringContaining('guided-katy-perry-2026'),
      expect.stringContaining('guided-katy-perry-2019'),
      expect.stringContaining('guided-katy-perry-2016'),
    ]);
    const justinPhotos = getGuidedPerson(scenario, JUSTIN).galleryPhotos;
    expect(justinPhotos).toHaveLength(2);
    expect(justinPhotos.map((photo) => photo.src)).toEqual([
      expect.stringContaining('guided-justin-trudeau-2025'),
      expect.stringContaining('guided-justin-trudeau-2025-b'),
    ]);
    expect(justinPhotos.every((photo) => photo.src.trim() !== '')).toBe(true);
    expect(new Set(justinPhotos.map((photo) => photo.src)).size).toBe(justinPhotos.length);
    expect(justinPhotos.map((photo) => photo.credit)).toEqual([
      '© European Union, 2025, EU reuse licence, resized',
      '© European Union, 2025, EU reuse licence, resized',
    ]);
    for (const person of scenario.people) {
      expect(person.galleryPhotos.length).toBeLessThanOrEqual(person.savedPhotoCount);
      for (const photo of person.galleryPhotos) {
        expect(photo.altText).toContain(person.name);
        expect(photo.credit).not.toBe('');
      }
    }

    expect(getGuidedFace(scenario, JUSTIN)).toEqual({
      id: JUSTIN,
      position: 'left',
      box: { x: 514, y: 77, width: 132, height: 189 },
      matchedPersonKey: JUSTIN,
      similarity: 0.686,
      strength: 'strong',
      source: 'saved-run',
    });
    expect(getGuidedFace(scenario, KATY)).toEqual({
      id: KATY,
      position: 'right',
      box: { x: 707, y: 140, width: 121, height: 181 },
      matchedPersonKey: KATY,
      similarity: 0.742,
      strength: 'strong',
      note: 'Her face is turned a little to the side.',
      source: 'saved-run',
    });

    expect(scenario.pressPhoto.src).toContain('guided-press-tribeca-2026');
    expect(scenario.pressPhoto.altText).toBe('Two people at a film festival.');
    expect(scenario.pressPhoto.credit).toBe('Colleen Sturtevant, CC BY-SA 4.0, resized');
    expect(scenario.pressPhoto.event).toBe('Tribeca Festival, New York, June 2026');
    expect(scenario.appliedText).toBe(scenario.pressPhoto.altText);
    expect(scenario.provenance).toEqual({
      service: 'AltContext recognition service (dev build)',
      model: 'InsightFace buffalo_l',
      runDate: '2026-09-06',
      threshold: 0.6,
      note: 'Saved from a real run. The demo does not run recognition live.',
      alsoChecked:
        'A Coachella press photo of the same two people matched both, even with a hand over her mouth. It is not bundled because of licensing.',
    });
    expect(scenario.visualFacts).toHaveLength(4);
    expect(scenario.candidate).toEqual({ text: scenario.drafts.none, status: GUIDED_CANDIDATE_STATUS.READY });
    expect(scenario.drafts.none).not.toMatch(/Katy Perry|Justin Trudeau/);
    expect(scenario.history).toEqual([]);
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
  });

  it('keeps every draft coherent: names only where confirmed, visual details everywhere', () => {
    const { drafts } = createGuidedScenario();

    expect(drafts.both).toBe(
      'Justin Trudeau and Katy Perry pose side by side at the Tribeca Festival. He wears a black tuxedo with a white shirt; she wears a white draped gown with her dark hair pinned up and rests a hand on his chest.',
    );
    expect(drafts['katy-perry']).toContain('Katy Perry');
    expect(drafts['katy-perry']).not.toContain('Justin Trudeau');
    expect(drafts['justin-trudeau']).toContain('Justin Trudeau');
    expect(drafts['justin-trudeau']).not.toContain('Katy Perry');
    for (const text of Object.values(drafts)) {
      expect(text).toContain('Tribeca Festival');
      expect(text).toContain('hand');
    }
  });

  it('picks the draft from the set of confirmed face matches', () => {
    const start = createGuidedScenario();
    expect(draftKeyFor(start)).toBe('none');
    expect(confirmedPersonKeys(start)).toEqual([]);

    const katyOnly = confirmGuidedIdentity(start, KATY);
    expect(draftKeyFor(katyOnly)).toBe('katy-perry');
    expect(confirmedPersonKeys(katyOnly)).toEqual([KATY]);
    expect(katyOnly.candidate).toEqual({
      text: katyOnly.drafts['katy-perry'],
      status: GUIDED_CANDIDATE_STATUS.READY,
    });
    expect(getGuidedIdentity(katyOnly, KATY)).toEqual({
      faceId: KATY,
      status: GUIDED_IDENTITY_STATUS.CONFIRMED,
      name: 'Katy Perry',
      source: 'face-match',
    });
    expect(getGuidedIdentity(katyOnly, JUSTIN)).toEqual({
      faceId: JUSTIN,
      status: GUIDED_IDENTITY_STATUS.UNCONFIRMED,
      source: 'none',
    });
    expect(katyOnly.history).toEqual([{ kind: 'identity-confirmed', faceId: KATY }]);
    expect(katyOnly.appliedText).toBe(start.appliedText);

    const both = confirmGuidedIdentity(katyOnly, JUSTIN);
    expect(draftKeyFor(both)).toBe('both');
    expect(confirmedPersonKeys(both)).toEqual([KATY, JUSTIN]);
    expect(draftFor(both)).toBe(both.drafts.both);
    expect(both.candidate.text).toContain('Justin Trudeau and Katy Perry');

    const justinOnly = confirmGuidedIdentity(start, JUSTIN);
    expect(draftKeyFor(justinOnly)).toBe('justin-trudeau');
  });

  it('keeps an unnamed person out of the draft and lets the other name stay', () => {
    const scenario = leaveGuidedIdentityUnidentified(confirmGuidedIdentity(createGuidedScenario(), JUSTIN), KATY);

    expect(getGuidedIdentity(scenario, KATY)).toEqual({
      faceId: KATY,
      status: GUIDED_IDENTITY_STATUS.UNIDENTIFIED,
      source: 'none',
    });
    expect(draftKeyFor(scenario)).toBe('justin-trudeau');
    expect(scenario.candidate.text).not.toContain('Katy Perry');
    expect(scenario.candidate.text).toContain('Justin Trudeau');
    expect(scenario.history).toEqual([
      { kind: 'identity-confirmed', faceId: JUSTIN },
      { kind: 'identity-unidentified', faceId: KATY },
    ]);

    const nobody = leaveGuidedIdentityUnidentified(scenario, JUSTIN);
    expect(draftKeyFor(nobody)).toBe('none');
    expect(nobody.candidate).toEqual({ text: nobody.drafts.none, status: GUIDED_CANDIDATE_STATUS.READY });
  });

  it('drops an unsaved edit when an identity answer changes', () => {
    const edited = saveGuidedEdit(createGuidedScenario(), 'Two people on a red carpet.');
    expect(edited.candidate).toEqual({
      text: 'Two people on a red carpet.',
      status: GUIDED_CANDIDATE_STATUS.EDITED,
    });

    const confirmed = confirmGuidedIdentity(edited, KATY);
    expect(confirmed.candidate).toEqual({
      text: confirmed.drafts['katy-perry'],
      status: GUIDED_CANDIDATE_STATUS.READY,
    });
  });

  it('refuses a name in a saved edit or an apply until that face match is confirmed', () => {
    const start = createGuidedScenario();
    expect(nameGuardError('Katy Perry')).toBe(
      'You can only use the name Katy Perry after you confirm that face match.',
    );

    expect(() => saveGuidedEdit(start, 'katy perry on the red carpet')).toThrow(nameGuardError('Katy Perry'));
    expect(() => saveGuidedEdit(start, 'Justin Trudeau on the red carpet')).toThrow(nameGuardError('Justin Trudeau'));

    const katyOnly = confirmGuidedIdentity(start, KATY);
    expect(() => saveGuidedEdit(katyOnly, 'Katy Perry with Justin Trudeau.')).toThrow(nameGuardError('Justin Trudeau'));
    const saved = saveGuidedEdit(katyOnly, 'Katy Perry with a man in a tuxedo.');
    expect(saved.candidate.status).toBe(GUIDED_CANDIDATE_STATUS.EDITED);

    const unnamedKaty = leaveGuidedIdentityUnidentified(katyOnly, KATY);
    expect(() => saveGuidedEdit(unnamedKaty, 'Katy Perry again')).toThrow(nameGuardError('Katy Perry'));
  });

  it('guards applying a draft that names an unconfirmed person', () => {
    const start = createGuidedScenario();
    const forged = {
      ...start,
      candidate: { text: start.drafts['katy-perry'], status: GUIDED_CANDIDATE_STATUS.READY },
    };

    expect(() => applyGuidedCandidate(forged)).toThrow(nameGuardError('Katy Perry'));
  });

  it('keeps editing and rejection separate from explicit application, then supports undo', () => {
    const both = confirmGuidedIdentity(confirmGuidedIdentity(createGuidedScenario(), JUSTIN), KATY);

    const rejected = rejectGuidedCandidate(both);
    expect(rejected.candidate.status).toBe(GUIDED_CANDIDATE_STATUS.REJECTED);
    expect(rejected.appliedText).toBe(both.appliedText);
    expect(() => applyGuidedCandidate(rejected)).toThrow('Cannot apply a rejected description.');

    const applied = applyGuidedCandidate(both);
    expect(applied.appliedText).toBe(both.drafts.both);
    expect(getLastGuidedApplication(applied.history)).toEqual({
      kind: 'applied',
      text: both.drafts.both,
      previousAppliedText: 'Two people at a film festival.',
    });

    const undone = undoGuidedApplication(applied);
    expect(undone.appliedText).toBe('Two people at a film festival.');
    expect(undone.history.at(-1)).toEqual({ kind: 'application-undone', text: 'Two people at a film festival.' });
    expect(getLastGuidedApplication(undone.history)).toBeUndefined();
    expect(undoGuidedApplication(undone)).toEqual(undone);
  });

  it('moves a rejected candidate back to edited before applying the saved edit', () => {
    const both = confirmGuidedIdentity(confirmGuidedIdentity(createGuidedScenario(), JUSTIN), KATY);
    const rejected = rejectGuidedCandidate(both);
    expect(rejected.candidate.status).toBe(GUIDED_CANDIDATE_STATUS.REJECTED);

    const edited = saveGuidedEdit(rejected, 'A new description for the photo.');
    expect(edited.candidate.status).toBe(GUIDED_CANDIDATE_STATUS.EDITED);

    const applied = applyGuidedCandidate(edited);
    expect(applied.candidate.status).toBe(GUIDED_CANDIDATE_STATUS.EDITED);
    expect(applied.appliedText).toBe('A new description for the photo.');
    expect(applied.history.at(-1)).toEqual({
      kind: 'applied',
      text: 'A new description for the photo.',
      previousAppliedText: both.appliedText,
    });
  });

  it('treats applying the already-applied text as an idempotent action', () => {
    const scenario = createGuidedScenario();
    const same = saveGuidedEdit(scenario, scenario.appliedText);
    const applied = applyGuidedCandidate(same);

    expect(applied.appliedText).toBe(scenario.appliedText);
    expect(applied.history).toEqual(same.history);
  });

  it('consumes applications in LIFO order and restores each prior applied value', () => {
    const first = applyGuidedCandidate(confirmGuidedIdentity(createGuidedScenario(), JUSTIN));
    const second = applyGuidedCandidate(confirmGuidedIdentity(first, KATY));
    expect(second.appliedText).toBe(second.drafts.both);

    const undoOnce = undoGuidedApplication(second);
    expect(undoOnce.appliedText).toBe(second.drafts['justin-trudeau']);
    const undoTwice = undoGuidedApplication(undoOnce);
    expect(undoTwice.appliedText).toBe('Two people at a film festival.');
    expect(undoGuidedApplication(undoTwice).appliedText).toBe('Two people at a film festival.');
  });

  it('rejects an empty description', () => {
    expect(() => saveGuidedEdit(createGuidedScenario(), '   ')).toThrow('A description cannot be empty.');
  });

  it('never mutates the input scenario and keeps practice instances isolated', () => {
    const a = createGuidedScenario();
    const snapshot = JSON.stringify(a);
    const b = confirmGuidedIdentity(a, KATY);
    saveGuidedEdit(b, 'Katy Perry waves.');
    applyGuidedCandidate(b);

    expect(JSON.stringify(a)).toBe(snapshot);
    expect(b.faces).not.toBe(a.faces);
    expect(getGuidedFace(b, KATY).box).not.toBe(getGuidedFace(a, KATY).box);
    expect(b.identities).not.toBe(a.identities);
  });

  it('resets to a fresh scenario without carrying decisions forward', () => {
    const used = applyGuidedCandidate(confirmGuidedIdentity(createGuidedScenario(), KATY));
    const fresh = resetGuidedScenario();

    expect(fresh.history).toEqual([]);
    expect(fresh.identities.every((identity) => identity.status === GUIDED_IDENTITY_STATUS.UNCONFIRMED)).toBe(true);
    expect(fresh.appliedText).toBe('Two people at a film festival.');
    expect(fresh).not.toBe(used);
  });
});
