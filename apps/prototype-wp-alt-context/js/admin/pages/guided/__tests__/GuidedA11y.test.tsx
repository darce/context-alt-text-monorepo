/**
 * W04 semantic, keyboard, and announcement verification for the guided demo.
 *
 * Journey and reducer coverage lives in GuidedPrototypePage.test.tsx (and the
 * live-panel tests). This file does not repeat those assertions except where an
 * accessibility observation would prove the shipped page wrong (P2).
 */
import React from 'react';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';

import { guidedCopy } from '../../../guidedPrototype/copy';
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
      ? guidedCopy('names.include', { name: position === 'left' ? 'Justin Trudeau' : 'Katy Perry' })
      : guidedCopy('names.omit');
  const radio = within(fieldset).getByRole('radio', { name });
  await user.click(radio);
  return radio;
};

const stepButton = (step: 'context' | 'names' | 'draft' | 'apply'): HTMLElement =>
  within(screen.getByTestId('guided-demo-stepper')).getByRole('button', {
    name: guidedCopy(`step.${step}`),
  });

const completeCoreDraft = async (user: ReturnType<typeof userEvent.setup>, draft: string): Promise<void> => {
  await chooseRadio(user, 'tribeca', 'left', 'include');
  await chooseRadio(user, 'tribeca', 'right', 'include');
  const review = screen.getByTestId('guided-description-review-tribeca');
  const editor = within(review).getByRole('textbox', { name: guidedCopy('draft.label') });
  await user.clear(editor);
  await user.type(editor, draft);
  await user.click(within(review).getByRole('button', { name: guidedCopy('draft.next') }));
  await user.click(screen.getByTestId('demo-apply-tribeca'));
};

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

  it('would prove the page wrong if more than one h1 existed, the h1 were not page.title, or a step lacked an h2', () => {
    render(<GuidedPrototypePage />);

    const titles = screen.getAllByRole('heading', { level: 1 });
    expect(titles).toHaveLength(1);
    expect(titles[0]).toHaveTextContent(guidedCopy('page.title'));

    const stepTitles = [
      guidedCopy('step.context'),
      guidedCopy('step.names'),
      guidedCopy('step.draft'),
      guidedCopy('step.apply'),
    ];
    stepTitles.forEach((title) => {
      expect(screen.getByRole('heading', { level: 2, name: title })).toBeInTheDocument();
    });
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

      const cards = within(photo).getAllByRole('region', { name: /Saved suggestion:/ });
      expect(cards).toHaveLength(2);
      const leftCard = within(photo).getByRole('region', {
        name: guidedCopy('names.suggestion', { name: 'Justin Trudeau' }),
      });
      const rightCard = within(photo).getByRole('region', {
        name: guidedCopy('names.suggestion', { name: 'Katy Perry' }),
      });
      expect(within(leftCard).getByText(guidedCopy('names.pending'))).toBeInTheDocument();
      expect(within(rightCard).getByText(guidedCopy('names.pending'))).toBeInTheDocument();
    });

    for (const photoKey of photoKeys) {
      const photo = screen.getByTestId(`guided-photo-${photoKey}`);
      const leftCard = within(photo).getByRole('region', {
        name: guidedCopy('names.suggestion', { name: 'Justin Trudeau' }),
      });
      const rightCard = within(photo).getByRole('region', {
        name: guidedCopy('names.suggestion', { name: 'Katy Perry' }),
      });
      const includeLeft = await chooseRadio(user, photoKey, 'left', 'include');
      expect(includeLeft).toBeChecked();
      expect((includeLeft as HTMLInputElement).checked).toBe(true);
      expect(within(leftCard).getByText(guidedCopy('names.included', { name: 'Justin Trudeau' }))).toBeInTheDocument();

      const omitRight = await chooseRadio(user, photoKey, 'right', 'omit');
      expect(omitRight).toBeChecked();
      expect(within(rightCard).getByText(guidedCopy('names.omitted'))).toBeInTheDocument();
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
    expect(indexOfStop(stops, guidedCopy('guide.hide'))).toBeLessThan(indexOfStop(stops, guidedCopy('step.context')));
    expect(indexOfStop(stops, guidedCopy('step.context'))).toBeLessThan(indexOfStop(stops, guidedCopy('step.names')));
    expect(indexOfStop(stops, guidedCopy('step.names'))).toBeLessThan(indexOfStop(stops, guidedCopy('step.draft')));
    expect(indexOfStop(stops, guidedCopy('step.draft'))).toBeLessThan(indexOfStop(stops, guidedCopy('step.apply')));
    const leftInclude = guidedCopy('names.include', { name: 'Justin Trudeau' });
    const rightInclude = guidedCopy('names.include', { name: 'Katy Perry' });
    const photoKeys: GuidedImageKey[] = ['tribeca', 'coachella'];
    for (const photoKey of photoKeys) {
      const leftStop = photoStop(photoKey, leftInclude);
      const rightStop = photoStop(photoKey, rightInclude);
      expect(indexOfStop(stops, guidedCopy('step.apply'))).toBeLessThan(indexOfStop(stops, leftStop));
      expect(indexOfStop(stops, leftStop)).toBeLessThan(indexOfStop(stops, rightStop));
      expect(indexOfStop(stops, rightStop)).toBeLessThan(indexOfStop(stops, guidedCopy('live.submit')));
    }

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

  it('would prove the page wrong if a guide or next-step control failed to move focus to its section target', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: guidedCopy('page.start') }));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-understand');
    expect(document.activeElement).toHaveAccessibleName(guidedCopy('step.context'));

    await user.click(stepButton('names'));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-face');
    expect(document.activeElement).toHaveAccessibleName(guidedCopy('step.names'));

    await user.click(screen.getByRole('button', { name: guidedCopy('context.next') }));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-face');
    expect(document.activeElement).toHaveAccessibleName(guidedCopy('step.names'));

    await chooseRadio(user, 'tribeca', 'left', 'include');
    await chooseRadio(user, 'tribeca', 'right', 'include');
    await user.click(screen.getByRole('button', { name: guidedCopy('names.next') }));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-review');
    expect(document.activeElement).toHaveAccessibleName(guidedCopy('step.draft'));

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
    const evidenceAlt = requireSample('none');
    const edited = 'Byte-for-byte applied festival sentence.';

    const evidence = screen.getByRole('img', { name: evidenceAlt });
    await chooseRadio(user, 'tribeca', 'left', 'include');
    await chooseRadio(user, 'tribeca', 'right', 'include');
    const applied = screen.getByTestId('demo-applied-image-tribeca');
    expect(applied).not.toBe(evidence);
    expect(applied).toHaveAttribute('alt', SEED_ALT_TEXT);
    expect(applied).not.toHaveAttribute('aria-label');

    await completeCoreDraft(user, edited);
    expect(screen.getByTestId('demo-applied-image-tribeca')).toHaveAttribute('alt', edited);
    expect(screen.getByRole('img', { name: evidenceAlt })).toHaveAttribute('alt', evidenceAlt);
    expect(screen.getByRole('img', { name: evidenceAlt })).not.toBe(screen.getByTestId('demo-applied-image-tribeca'));
  });

  it('would prove the page wrong if demo-applied-image reused the evidence photo src', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);
    const evidenceAlt = requireSample('none');
    const evidence = screen.getByRole('img', { name: evidenceAlt });
    await chooseRadio(user, 'tribeca', 'left', 'include');
    await chooseRadio(user, 'tribeca', 'right', 'include');
    const applied = screen.getByTestId('demo-applied-image-tribeca');
    expect(applied.getAttribute('src')).not.toBe(evidence.getAttribute('src'));
  });

  it('would prove the page wrong if step navigation replaced #/guided-prototype with a section hash', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: guidedCopy('page.start') }));
    expect(window.location.hash).toBe('#/guided-prototype');
    await user.click(stepButton('names'));
    expect(window.location.hash).toBe('#/guided-prototype');
    await user.click(stepButton('draft'));
    expect(window.location.hash).toBe('#/guided-prototype');
    await user.click(stepButton('apply'));
    expect(window.location.hash).toBe('#/guided-prototype');
    expect(window.location.hash).not.toMatch(/guided-section-/);
  });

  it('would prove the page wrong if the core walkthrough needed a live network call or failed when the live stub rejected', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);
    const edited = 'Core path with rejecting live stub.';

    await completeCoreDraft(user, edited);
    expect(screen.getByTestId('demo-applied-image-tribeca')).toHaveAttribute('alt', edited);
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
    const leftSummary = within(tribecaPhoto).getByText(guidedCopy('names.evidence_open', { position: 'left' }));
    leftSummary.focus();
    await user.keyboard('{Enter}');
    expect(within(tribecaPhoto).getByText(guidedCopy('names.coverage_all', { total: 3 }))).toBeInTheDocument();

    const rightSummary = within(tribecaPhoto).getByText(guidedCopy('names.evidence_open', { position: 'right' }));
    rightSummary.focus();
    await user.keyboard('{Enter}');
    expect(
      within(tribecaPhoto).getByText(guidedCopy('names.coverage_partial', { shown: 3, total: 5 })),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Show all 5/)).not.toBeInTheDocument();
  });

  it('would prove the page wrong if the face comparison had no keyboard-operable enlarged view of the crop or references', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    const tribecaPhoto = screen.getByTestId('guided-photo-tribeca');
    await user.click(within(tribecaPhoto).getByText(guidedCopy('names.evidence_open', { position: 'left' })));
    const enlargeButtons = within(tribecaPhoto).getAllByRole('button', { name: guidedCopy('names.enlarge') });
    expect(enlargeButtons).toHaveLength(2);
    expect(screen.getAllByRole('img', { name: /Detected left face in/ })).toHaveLength(2);
    expect(screen.getAllByRole('img', { name: /Detected right face in/ })).toHaveLength(2);

    const leftCard = within(tribecaPhoto).getByRole('region', {
      name: guidedCopy('names.suggestion', { name: 'Justin Trudeau' }),
    });
    const enlarge = within(leftCard).getByRole('button', { name: guidedCopy('names.enlarge') });
    await user.click(enlarge);
    const comparison = screen.getByRole('dialog', { name: guidedCopy('names.enlarge_title') });
    expect(comparison).toHaveAttribute('aria-modal', 'true');
    await user.click(within(comparison).getByRole('button', { name: guidedCopy('names.evidence_close') }));
    expect(screen.queryByRole('dialog', { name: guidedCopy('names.enlarge_title') })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(enlarge);

    enlarge.focus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('dialog', { name: guidedCopy('names.enlarge_title') })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: guidedCopy('names.enlarge_title') })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(enlarge);
  });
});
