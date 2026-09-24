/**
 * W04 semantic, keyboard, and announcement verification for the guided demo.
 *
 * Journey and reducer coverage lives in GuidedPrototypePage.test.tsx (and the
 * live-panel tests). This file does not repeat those assertions except where an
 * accessibility observation would prove the shipped page wrong (P2).
 */
import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';

import { guidedCopy } from '../../../guidedPrototype/copy';
import { guidedCopy as publicGuidedCopy } from '../../../guidedPrototype/publicGuideCopy';
import { createGuidedScenario, type GuidedImageKey } from '../../../guidedPrototype/state';
import type { GuidedLiveDescriptionClient } from '../../../guidedPrototype/useGuidedLiveDescription';
import type { GuidedLiveDescriptionPanelProps } from '../GuidedLiveDescriptionPanel';
import { GuidedPrototypePage } from '../GuidedPrototypePage';

const STUB_REJECT = new Error('GUIDEDQM-1 live stub reject');
const NETWORK_BLOCKED = new Error('GUIDEDQM-1 network blocked');
const LIVE_MEDIA_ID = 4211;
const SEED_ALT_TEXT =
  'A man in a black suit and a woman in a white dress pose together, smiling, in front of a Tribeca Festival step-and-repeat backdrop.';
const SCENARIO = createGuidedScenario();

const liveClient = vi.hoisted((): { [K in keyof GuidedLiveDescriptionClient]: Mock } => {
  const reject = (): Promise<never> => Promise.reject(STUB_REJECT);
  return {
    submit: vi.fn(reject),
    poll: vi.fn(reject),
    items: vi.fn(reject),
    cancel: vi.fn(reject),
  };
});

vi.mock('../GuidedLiveDescriptionPanel', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../GuidedLiveDescriptionPanel')>();
  const GuidedLiveDescriptionPanel = (props: GuidedLiveDescriptionPanelProps): React.JSX.Element =>
    React.createElement(actual.GuidedLiveDescriptionPanel, {
      ...props,
      mediaId: LIVE_MEDIA_ID,
      client: liveClient,
    });
  return { ...actual, GuidedLiveDescriptionPanel };
});

const assertHtmlElement: (value: EventTarget | Node | null, description: string) => asserts value is HTMLElement = (
  value,
  description,
) => {
  if (!(value instanceof HTMLElement)) {
    throw new Error(`Expected ${description} to be an HTMLElement`);
  }
};

const assertNonEmptyString: (value: string | null | undefined, description: string) => asserts value is string = (
  value,
  description,
) => {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`Expected ${description} to be a non-empty string`);
  }
};

const requireSample = (key: 'none' | 'both' | 'justin-trudeau' | 'katy-perry'): string => {
  const value = SCENARIO.samples.tribeca[key];
  assertNonEmptyString(value, `scenario.samples[${key}]`);
  return value;
};

const controlKey = (element: HTMLElement): string => {
  const photoScope = element.closest<HTMLElement>('[data-testid^="guided-photo-"]')?.getAttribute('data-testid');
  const scope = (key: string): string =>
    photoScope === null || photoScope === undefined ? key : `${photoScope}:${key}`;
  const ariaLabel = element.getAttribute('aria-label');
  if (ariaLabel) {
    return scope(ariaLabel);
  }
  if (element instanceof HTMLInputElement && element.labels?.[0] !== undefined) {
    return scope((element.labels[0].textContent ?? '').replace(/\s+/g, ' ').trim());
  }
  if (element.id.length > 0) {
    return scope(`#${element.id}`);
  }
  const testId = element.getAttribute('data-testid');
  if (testId) {
    return scope(testId);
  }
  const text = (element.textContent ?? '').replace(/\s+/g, ' ').trim();
  return scope(`${element.tagName}:${text.slice(0, 48)}`);
};

const photoStop = (photoKey: GuidedImageKey, label: string): string => `guided-photo-${photoKey}:${label}`;

const indexOfStop = (stops: string[], needle: string): number => {
  const index = stops.findIndex((stop) => stop.includes(needle));
  if (index < 0) {
    throw new Error(`Tab order never reached ${needle}. Stops: ${stops.join(' -> ')}`);
  }
  return index;
};

const politeRegions = (): HTMLElement[] =>
  Array.from(document.querySelectorAll<HTMLElement>('[aria-live="polite"], [role="status"]'));

const politeSnapshot = (): Map<string, string> => {
  const snapshot = new Map<string, string>();
  politeRegions().forEach((region, index) => {
    const key =
      (region.getAttribute('data-testid') ?? region.getAttribute('aria-label') ?? region.id) || `region-${index}`;
    snapshot.set(key, (region.textContent ?? '').replace(/\s+/g, ' ').trim());
  });
  return snapshot;
};

const changedPoliteTexts = (before: Map<string, string>, after: Map<string, string>): string[] => {
  const changed: string[] = [];
  after.forEach((text, key) => {
    if (before.get(key) !== text) {
      changed.push(text);
    }
  });
  return changed;
};

const chooseRadio = async (
  user: ReturnType<typeof userEvent.setup>,
  photoKey: GuidedImageKey,
  position: 'left' | 'right',
  option: 'include' | 'omit',
): Promise<HTMLElement> => {
  const photo = screen.getByTestId(`guided-photo-${photoKey}`);
  const fieldset = within(photo).getByRole('group', { name: guidedCopy('names.legend', { position }) });
  const name =
    option === 'include'
      ? publicGuidedCopy('names.use.public', { name: position === 'left' ? 'Justin Trudeau' : 'Katy Perry' })
      : publicGuidedCopy('names.omit.public');
  const radio = within(fieldset).getByRole('radio', { name });
  await user.click(radio);
  return radio;
};

const completePhotoDraft = async (
  user: ReturnType<typeof userEvent.setup>,
  photoKey: GuidedImageKey,
  draft: string,
): Promise<void> => {
  await chooseRadio(user, photoKey, 'left', 'include');
  await chooseRadio(user, photoKey, 'right', 'include');
  const review = screen.getByTestId(`guided-description-review-${photoKey}`);
  const editor = within(review).getByRole('textbox', { name: guidedCopy('draft.label') });
  await user.clear(editor);
  await user.type(editor, draft);
  await user.click(within(review).getByRole('button', { name: guidedCopy('draft.next') }));
  await user.click(screen.getByTestId(`demo-apply-${photoKey}`));
};

const completeCoreDraft = async (user: ReturnType<typeof userEvent.setup>, draft: string): Promise<void> =>
  completePhotoDraft(user, 'tribeca', draft);

describe('GuidedA11y (W04)', () => {
  let fetchSpy: Mock;

  beforeEach(() => {
    window.location.hash = '#/guided-prototype';
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.reject(NETWORK_BLOCKED));
    liveClient.submit.mockClear();
    liveClient.poll.mockClear();
    liveClient.items.mockClear();
    liveClient.cancel.mockClear();
  });

  afterEach(() => {
    cleanup();
    fetchSpy.mockRestore();
    window.location.hash = '';
  });

  it('would prove the page wrong if more than one h1 existed, the h1 were not page.title, or a photo step lacked its heading', () => {
    render(<GuidedPrototypePage />);

    const titles = screen.getAllByRole('heading', { level: 1 });
    expect(titles).toHaveLength(1);
    expect(titles[0]).toHaveTextContent(guidedCopy('page.title'));

    const photoKeys: GuidedImageKey[] = ['tribeca', 'coachella'];
    photoKeys.forEach((photoKey, index) => {
      const photoStep = screen.getByTestId(`guided-photo-step-${photoKey}`);
      expect(
        within(photoStep).getByRole('heading', {
          level: 3,
          name: publicGuidedCopy('photo.count.public', { photoNumber: index + 1 }),
        }),
      ).toBeInTheDocument();
      expect(
        within(screen.getByTestId(`guided-faces-${photoKey}`)).getByRole('heading', {
          level: 4,
          name: publicGuidedCopy('names.heading.public'),
        }),
      ).toBeInTheDocument();
      expect(
        within(screen.getByTestId(`guided-description-step-${photoKey}`)).getByRole('heading', {
          level: 4,
          name: publicGuidedCopy('description.heading.public'),
        }),
      ).toBeInTheDocument();
    });
    expect(screen.queryByRole('heading', { name: guidedCopy('step.context') })).not.toBeInTheDocument();
    expect(screen.queryByText(/How two faces become two names/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Matched to Justin Trudeau/)).not.toBeInTheDocument();
  });

  it('would prove the page wrong if a name group were not a native fieldset/legend, started preselected, or hid selected state', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    const photoKeys: GuidedImageKey[] = ['tribeca', 'coachella'];
    photoKeys.forEach((photoKey) => {
      const photo = screen.getByTestId(`guided-photo-${photoKey}`);
      const left = within(photo).getByRole('group', { name: guidedCopy('names.legend', { position: 'left' }) });
      const right = within(photo).getByRole('group', { name: guidedCopy('names.legend', { position: 'right' }) });
      expect(left.tagName).toBe('FIELDSET');
      expect(right.tagName).toBe('FIELDSET');
      expect(left.querySelector('legend')).toHaveTextContent(guidedCopy('names.legend', { position: 'left' }));
      expect(right.querySelector('legend')).toHaveTextContent(guidedCopy('names.legend', { position: 'right' }));

      const leftRadios = within(left).getAllByRole('radio');
      const rightRadios = within(right).getAllByRole('radio');
      expect(leftRadios.every((radio) => (radio as HTMLInputElement).checked === false)).toBe(true);
      expect(rightRadios.every((radio) => (radio as HTMLInputElement).checked === false)).toBe(true);

      const leftCard = within(photo).getByRole('region', {
        name: 'Justin Trudeau',
      });
      const rightCard = within(photo).getByRole('region', {
        name: 'Katy Perry',
      });
      expect(
        within(leftCard).getByRole('radio', { name: publicGuidedCopy('names.use.public', { name: 'Justin Trudeau' }) }),
      ).toBeVisible();
      expect(
        within(rightCard).getByRole('radio', { name: publicGuidedCopy('names.use.public', { name: 'Katy Perry' }) }),
      ).toBeVisible();
    });

    for (const photoKey of photoKeys) {
      const photo = screen.getByTestId(`guided-photo-${photoKey}`);
      const leftCard = within(photo).getByRole('region', {
        name: 'Justin Trudeau',
      });
      const rightCard = within(photo).getByRole('region', {
        name: 'Katy Perry',
      });
      const includeLeft = await chooseRadio(user, photoKey, 'left', 'include');
      expect(includeLeft).toBeChecked();
      expect((includeLeft as HTMLInputElement).checked).toBe(true);
      expect(
        within(leftCard).getByRole('radio', { name: publicGuidedCopy('names.use.public', { name: 'Justin Trudeau' }) }),
      ).toBeChecked();

      const omitRight = await chooseRadio(user, photoKey, 'right', 'omit');
      expect(omitRight).toBeChecked();
      expect(within(rightCard).getByRole('radio', { name: publicGuidedCopy('names.omit.public') })).toBeChecked();
    }
  });

  it('would prove the page wrong if Tab order diverged from DOM order, a positive tabindex existed, or a trap appeared outside the reset dialog', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    const positiveTabIndex = Array.from(document.querySelectorAll<HTMLElement>('[tabindex]')).filter(
      (element) => element.tabIndex > 0,
    );
    expect(positiveTabIndex).toEqual([]);

    const stops: string[] = [];
    for (let index = 0; index < 32; index += 1) {
      await user.tab();
      const active = document.activeElement;
      if (!(active instanceof HTMLElement) || active === document.body) {
        break;
      }
      stops.push(controlKey(active));
    }
    expect(new Set(stops).size).toBeGreaterThan(8);
    expect(indexOfStop(stops, guidedCopy('page.start'))).toBeLessThan(
      indexOfStop(stops, guidedCopy('page.case_study')),
    );
    const leftInclude = publicGuidedCopy('names.use.public', { name: 'Justin Trudeau' });
    const rightInclude = publicGuidedCopy('names.use.public', { name: 'Katy Perry' });
    const photoKeys: GuidedImageKey[] = ['tribeca', 'coachella'];
    expect(indexOfStop(stops, guidedCopy('page.case_study'))).toBeLessThan(
      indexOfStop(stops, guidedCopy('page.reset')),
    );
    for (const photoKey of photoKeys) {
      const leftStop = photoStop(photoKey, leftInclude);
      const rightStop = photoStop(photoKey, rightInclude);
      expect(indexOfStop(stops, guidedCopy('page.reset'))).toBeLessThan(indexOfStop(stops, leftStop));
      expect(indexOfStop(stops, leftStop)).toBeLessThan(indexOfStop(stops, rightStop));
      if (photoKey === 'tribeca') {
        expect(indexOfStop(stops, rightStop)).toBeLessThan(indexOfStop(stops, photoStop('coachella', leftInclude)));
      }
    }
    expect(indexOfStop(stops, photoStop('coachella', rightInclude))).toBeLessThan(
      indexOfStop(stops, guidedCopy('live.submit')),
    );

    const resetButton = screen.getByRole('button', { name: guidedCopy('page.reset') });
    await user.click(resetButton);
    const dialog = screen.getByRole('dialog', { name: guidedCopy('reset.title') });
    for (let index = 0; index < 6; index += 1) {
      await user.tab();
      assertHtmlElement(document.activeElement, `dialog tab stop ${index + 1}`);
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it('would prove the page wrong if choosing a name, restoring a revision, or cancelling reset moved focus without an explicit step action', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    const includeLeft = await chooseRadio(user, 'tribeca', 'left', 'include');
    expect(document.activeElement).toBe(includeLeft);
    await chooseRadio(user, 'tribeca', 'right', 'include');

    const edited = 'Visitor-edited festival alt text.';
    const review = screen.getByTestId('guided-description-review-tribeca');
    const editor = within(review).getByRole('textbox', { name: guidedCopy('draft.label') });
    await user.clear(editor);
    await user.type(editor, edited);
    await user.click(within(review).getByRole('button', { name: guidedCopy('draft.next') }));

    await chooseRadio(user, 'tribeca', 'right', 'omit');
    const replaceDialog = screen.getByRole('dialog', { name: guidedCopy('names.change_title') });
    await user.click(within(replaceDialog).getByRole('button', { name: guidedCopy('names.change_confirm') }));

    await chooseRadio(user, 'tribeca', 'right', 'include');
    await user.click(
      within(screen.getByRole('dialog', { name: guidedCopy('names.change_title') })).getByRole('button', {
        name: guidedCopy('names.change_confirm'),
      }),
    );
    const restore = within(review).getByRole('button', { name: guidedCopy('draft.restore_revision') });
    restore.focus();
    await user.click(restore);
    expect(document.activeElement).toBe(restore);

    const resetButton = screen.getByRole('button', { name: guidedCopy('page.reset') });
    await user.click(resetButton);
    await user.click(
      within(screen.getByRole('dialog', { name: guidedCopy('reset.title') })).getByRole('button', {
        name: guidedCopy('reset.cancel'),
      }),
    );
    expect(document.activeElement).toBe(resetButton);
  });

  it('would prove the page wrong if Undo moved focus away from the undo control', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await completeCoreDraft(user, 'First applied festival sentence.');
    const review = screen.getByTestId('guided-description-review-tribeca');
    const editor = within(review).getByRole('textbox', { name: guidedCopy('draft.label') });
    await user.clear(editor);
    await user.type(editor, 'Second applied festival sentence.');
    await user.click(within(review).getByRole('button', { name: guidedCopy('draft.next') }));
    await user.click(screen.getByTestId('demo-apply-tribeca'));

    const undo = screen.getByTestId('demo-undo-tribeca');
    expect(undo).toBeEnabled();
    undo.focus();
    await user.click(undo);
    expect(undo).toBeEnabled();
    expect(document.activeElement).toBe(undo);
  });

  it('would prove the page wrong if Start or a remaining next-step control failed to move focus to its target', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    const firstNameQuestion = within(screen.getByTestId('name-choice-tribeca-left')).getByRole('radio', {
      name: publicGuidedCopy('names.use.public', { name: 'Justin Trudeau' }),
    });
    const focusFirstNameQuestion = vi.spyOn(firstNameQuestion, 'focus');
    await user.click(screen.getByRole('button', { name: guidedCopy('page.start') }));
    expect(document.activeElement).toBe(firstNameQuestion);
    expect(focusFirstNameQuestion).toHaveBeenCalledWith({ preventScroll: true });

    await chooseRadio(user, 'tribeca', 'left', 'include');
    await chooseRadio(user, 'tribeca', 'right', 'include');
    await user.click(
      within(screen.getByTestId('guided-description-review-tribeca')).getByRole('button', {
        name: guidedCopy('draft.next'),
      }),
    );
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-apply');
    expect(document.activeElement).toHaveAccessibleName(guidedCopy('step.apply'));
  });

  it('would prove the page wrong if the reset dialog lacked role=dialog, a label, Escape-to-close, or onOpenChange', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    const resetButton = screen.getByRole('button', { name: guidedCopy('page.reset') });
    await user.click(resetButton);

    const dialog = screen.getByRole('dialog', { name: guidedCopy('reset.title') });
    expect(dialog).toHaveTextContent(guidedCopy('reset.body'));

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: guidedCopy('reset.title') })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(resetButton);
  });

  it('would prove the page wrong if the reset dialog omitted aria-modal', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: guidedCopy('page.reset') }));
    expect(screen.getByRole('dialog', { name: guidedCopy('reset.title') })).toHaveAttribute('aria-modal', 'true');
  });

  it('would prove the page wrong if choice, preview, apply, or undo emitted more than one polite live-region update or dumped the draft', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);
    const both = requireSample('both');
    const edited = 'Distinct polite-status festival sentence.';

    let before = politeSnapshot();
    await chooseRadio(user, 'tribeca', 'left', 'include');
    let changed = changedPoliteTexts(before, politeSnapshot());
    expect(changed).toHaveLength(1);
    expect(changed[0]).toBe(guidedCopy('names.included', { name: 'Justin Trudeau' }));
    expect(changed[0]).not.toContain(both);

    before = politeSnapshot();
    await chooseRadio(user, 'tribeca', 'right', 'include');
    changed = changedPoliteTexts(before, politeSnapshot());
    expect(changed).toHaveLength(1);
    expect(changed[0]).not.toContain(both);

    const review = screen.getByTestId('guided-description-review-tribeca');
    const editor = within(review).getByRole('textbox', { name: guidedCopy('draft.label') });
    await user.clear(editor);
    await user.type(editor, edited);

    before = politeSnapshot();
    await user.click(within(review).getByRole('button', { name: guidedCopy('draft.next') }));
    changed = changedPoliteTexts(before, politeSnapshot());
    expect(changed).toHaveLength(1);
    expect(changed[0]).toBe(guidedCopy('draft.next'));
    expect(changed[0]).not.toContain(edited);

    before = politeSnapshot();
    await user.click(screen.getByTestId('demo-apply-tribeca'));
    changed = changedPoliteTexts(before, politeSnapshot());
    expect(changed).toHaveLength(1);
    expect(changed[0]).toBe(guidedCopy('apply.success'));
    expect(changed[0]).not.toContain(edited);
    expect(screen.getByTestId('guided-page-feedback')).not.toHaveTextContent(edited);
    expect(screen.getByTestId('guided-page-feedback')).not.toHaveTextContent(guidedCopy('history.title'));

    before = politeSnapshot();
    await user.click(screen.getByTestId('demo-undo-tribeca'));
    changed = changedPoliteTexts(before, politeSnapshot());
    expect(changed).toHaveLength(1);
    expect(changed[0]).toBe(guidedCopy('apply.undone'));
    expect(changed[0]).not.toContain(edited);
  });

  it('would prove the page wrong if a live status change emitted more than one polite message or placed the live result in the live region', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByText(guidedCopy('live.title')));
    const before = politeSnapshot();
    await user.click(screen.getByRole('button', { name: guidedCopy('live.submit') }));
    await waitFor(() => {
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(guidedCopy('live.failed'));
    });
    const after = politeSnapshot();
    const changed = changedPoliteTexts(before, after);
    expect(changed).toHaveLength(1);
    expect(changed[0]).toContain(guidedCopy('live.failed'));
    expect(screen.getByTestId('guided-page-feedback')).not.toHaveTextContent(guidedCopy('live.failed'));
    expect(screen.queryByTestId('guided-live-text')).not.toBeInTheDocument();

    const liveRegion = screen.getByRole('status', { name: 'Live run status' });
    expect(liveRegion).toHaveAttribute('aria-live', 'polite');
    expect(liveRegion).not.toHaveTextContent(requireSample('both'));
    expect(liveRegion).not.toHaveTextContent(guidedCopy('history.empty'));
  });

  it('would prove the page wrong if demo-applied-image were the evidence node or its alt diverged from the applied sentence', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);
    const evidencePhoto = within(screen.getByTestId('guided-photo-tribeca'));
    const evidence = evidencePhoto.getByRole('img', { name: SEED_ALT_TEXT });
    const edited = 'Byte-for-byte applied festival sentence.';

    await chooseRadio(user, 'tribeca', 'left', 'include');
    await chooseRadio(user, 'tribeca', 'right', 'include');
    const applied = screen.getByTestId('demo-applied-image-tribeca');
    expect(applied).not.toBe(evidence);
    expect(applied).toHaveAttribute('alt', SEED_ALT_TEXT);
    expect(applied).not.toHaveAttribute('aria-label');

    await completeCoreDraft(user, edited);
    expect(screen.getByTestId('demo-applied-image-tribeca')).toHaveAttribute('alt', edited);
    expect(evidence).toHaveAttribute('alt', edited);
    expect(evidence).not.toBe(screen.getByTestId('demo-applied-image-tribeca'));
  });

  it('would prove the page wrong if demo-applied-image reused the evidence photo src', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);
    const evidence = within(screen.getByTestId('guided-photo-tribeca')).getByRole('img', { name: SEED_ALT_TEXT });
    await chooseRadio(user, 'tribeca', 'left', 'include');
    await chooseRadio(user, 'tribeca', 'right', 'include');
    const applied = screen.getByTestId('demo-applied-image-tribeca');
    expect(applied.getAttribute('src')).not.toBe(evidence.getAttribute('src'));
  });

  it('would prove the page wrong if walkthrough actions replaced #/guided-prototype with a section hash', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: guidedCopy('page.start') }));
    expect(window.location.hash).toBe('#/guided-prototype');
    await chooseRadio(user, 'tribeca', 'left', 'include');
    expect(window.location.hash).toBe('#/guided-prototype');
    await chooseRadio(user, 'tribeca', 'right', 'include');
    await user.click(
      within(screen.getByTestId('guided-description-review-tribeca')).getByRole('button', {
        name: guidedCopy('draft.next'),
      }),
    );
    expect(window.location.hash).toBe('#/guided-prototype');
    await user.click(screen.getByTestId('demo-apply-tribeca'));
    expect(window.location.hash).toBe('#/guided-prototype');
    expect(window.location.hash).not.toMatch(/guided-section-/);
  });

  it('would prove the page wrong if the core walkthrough needed a live network call or failed when the live stub rejected', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);
    const edited = 'Core path with rejecting live stub.';

    await completeCoreDraft(user, edited);
    await completePhotoDraft(user, 'coachella', 'Coachella photo description applied locally.');
    expect(screen.getByTestId('demo-applied-image-tribeca')).toHaveAttribute('alt', edited);
    expect(screen.getByTestId('demo-applied-image-coachella')).toHaveAttribute(
      'alt',
      'Coachella photo description applied locally.',
    );
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.applied'));
    expect(fetchSpy).not.toHaveBeenCalled();

    await user.click(screen.getByText(guidedCopy('live.title')));
    await user.click(screen.getByRole('button', { name: guidedCopy('live.submit') }));
    await waitFor(() => {
      expect(screen.getByTestId('guided-live-status')).toHaveTextContent(guidedCopy('live.failed'));
    });
    expect(liveClient.submit).toHaveBeenCalledTimes(1);
    expect(liveClient.submit).toHaveBeenCalledWith(LIVE_MEDIA_ID);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId('demo-applied-image-tribeca')).toHaveAttribute('alt', edited);
    expect(
      within(screen.getByTestId('guided-description-review-tribeca')).getByRole('textbox', {
        name: guidedCopy('draft.label'),
      }),
    ).toHaveValue(edited);
  });

  it('would prove the page wrong if a face comparison could not be opened from the keyboard or omitted an honest coverage count', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    const tribecaPhoto = screen.getByTestId('guided-photo-tribeca');
    const leftCard = within(tribecaPhoto).getByRole('region', { name: 'Justin Trudeau' });
    const leftCompare = within(leftCard).getByRole('button', { name: publicGuidedCopy('names.compare.public') });
    leftCompare.focus();
    await user.keyboard('{Enter}');
    const leftComparison = screen.getByRole('dialog', {
      name: publicGuidedCopy('lightbox.title.public', { name: 'Justin Trudeau' }),
    });
    expect(within(leftComparison).getByText(publicGuidedCopy('names.coverage_all', { total: 3 }))).toBeInTheDocument();
    await user.keyboard('{Escape}');

    const rightCard = within(tribecaPhoto).getByRole('region', { name: 'Katy Perry' });
    const rightCompare = within(rightCard).getByRole('button', { name: publicGuidedCopy('names.compare.public') });
    rightCompare.focus();
    await user.keyboard('{Enter}');
    const rightComparison = screen.getByRole('dialog', {
      name: publicGuidedCopy('lightbox.title.public', { name: 'Katy Perry' }),
    });
    expect(
      within(rightComparison).getByText(publicGuidedCopy('names.coverage_partial', { shown: 3, total: 5 })),
    ).toBeInTheDocument();
    expect(within(rightComparison).queryByText(/Show all 5/)).not.toBeInTheDocument();
  });

  it('would prove the page wrong if the face comparison had no keyboard-operable enlarged view of the crop or references', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    const tribecaPhoto = screen.getByTestId('guided-photo-tribeca');
    const leftCropAlt = publicGuidedCopy('names.crop_alt_image', {
      position: 'left',
      image: publicGuidedCopy('names.photo.tribeca'),
    });
    const leftCrop = within(tribecaPhoto).getByRole('img', { name: leftCropAlt });
    fireEvent.load(leftCrop);
    expect(leftCrop).toBeVisible();

    const leftCard = within(tribecaPhoto).getByRole('region', {
      name: 'Justin Trudeau',
    });
    const compare = within(leftCard).getByRole('button', { name: publicGuidedCopy('names.compare.public') });
    compare.focus();
    await user.keyboard('{Enter}');
    const comparison = screen.getByRole('dialog', {
      name: publicGuidedCopy('lightbox.title.public', { name: 'Justin Trudeau' }),
    });
    expect(comparison).toHaveAttribute('aria-modal', 'true');
    const enlargedCrop = within(comparison).getByRole('img', { name: leftCropAlt });
    fireEvent.load(enlargedCrop);
    expect(enlargedCrop).toBeVisible();
    expect(
      within(comparison).getByRole('region', {
        name: publicGuidedCopy('lightbox.references.public', { name: 'Justin Trudeau' }),
      }),
    ).toBeVisible();
    await user.click(within(comparison).getByRole('button', { name: publicGuidedCopy('lightbox.close.public') }));
    expect(
      screen.queryByRole('dialog', { name: publicGuidedCopy('lightbox.title.public', { name: 'Justin Trudeau' }) }),
    ).not.toBeInTheDocument();
    expect(document.activeElement).toBe(compare);

    compare.focus();
    await user.keyboard('{Enter}');
    expect(
      screen.getByRole('dialog', { name: publicGuidedCopy('lightbox.title.public', { name: 'Justin Trudeau' }) }),
    ).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(
      screen.queryByRole('dialog', { name: publicGuidedCopy('lightbox.title.public', { name: 'Justin Trudeau' }) }),
    ).not.toBeInTheDocument();
    expect(document.activeElement).toBe(compare);
  });
});
