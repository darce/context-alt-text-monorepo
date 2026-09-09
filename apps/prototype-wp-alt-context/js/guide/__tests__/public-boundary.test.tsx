import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CASE_STUDY_URL, guidedCopy } from '../../admin/guidedPrototype/copy';
import { RecordedWalkthrough } from '../../admin/guidedPrototype/RecordedWalkthrough';
import { createGuidedScenario } from '../../admin/guidedPrototype/state';

const SEED_ALT_TEXT = 'Two people at a film festival.';
const PUBLIC_SCOPE =
  'Try the review workflow using a recorded example. Your changes affect only the demo copy in this tab.';

const choose = (position: 'left' | 'right', option: 'include' | 'omit'): void => {
  const fieldset = screen.getByTestId(`name-choice-${position}`);
  const name =
    option === 'include'
      ? guidedCopy('names.include', { name: position === 'left' ? 'Justin Trudeau' : 'Katy Perry' })
      : guidedCopy('names.omit');
  fireEvent.click(within(fieldset).getByRole('radio', { name }));
};

const collectSources = (dir: string, acc: string[] = []): string[] => {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      collectSources(full, acc);
      continue;
    }
    if (full.endsWith('.ts') || full.endsWith('.tsx') || full.endsWith('.css')) {
      acc.push(full);
    }
  }
  return acc;
};

const importSpecifiers = (source: string): string[] => {
  const specs: string[] = [];
  const pattern = /(?:from|import)\s+['"]([^'"]+)['"]/g;
  for (const match of source.matchAll(pattern)) {
    specs.push(match[1]);
  }
  return specs;
};

describe('public recorded walkthrough boundary', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;
  let xhrOpen: ReturnType<typeof vi.spyOn>;
  let xhrSend: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
      throw new Error('public guide must not call fetch');
    });
    xhrOpen = vi.spyOn(XMLHttpRequest.prototype, 'open').mockImplementation(() => {
      throw new Error('public guide must not open XHR');
    });
    xhrSend = vi.spyOn(XMLHttpRequest.prototype, 'send').mockImplementation(() => {
      throw new Error('public guide must not send XHR');
    });
  });

  afterEach(() => {
    fetchSpy.mockRestore();
    xhrOpen.mockRestore();
    xhrSend.mockRestore();
  });

  it('renders the public scope text, entry actions, and escape hatch', () => {
    render(<RecordedWalkthrough scope="public" escapeHref="https://demo.example/" />);

    expect(screen.getByTestId('guided-scope')).toHaveTextContent(PUBLIC_SCOPE);
    expect(screen.getByRole('button', { name: guidedCopy('page.start') })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: guidedCopy('entry.watch') })).toHaveAttribute('href', CASE_STUDY_URL);
    expect(screen.getByRole('link', { name: guidedCopy('entry.read_case_study') })).toHaveAttribute(
      'href',
      CASE_STUDY_URL,
    );

    const escape = screen.getByRole('navigation', { name: guidedCopy('nav.leave') });
    expect(within(escape).getByRole('link', { name: guidedCopy('nav.home') })).toHaveAttribute(
      'href',
      'https://demo.example/',
    );
    expect(within(escape).getByRole('link', { name: guidedCopy('nav.case_study') })).toHaveAttribute(
      'href',
      CASE_STUDY_URL,
    );
    expect(screen.queryByTestId('guided-live')).not.toBeInTheDocument();
  });

  it('makes no network calls across choose → edit → preview → apply → undo', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" escapeHref="/" />);

    choose('left', 'include');
    choose('right', 'include');
    const edited = 'Public-tab festival description.';
    const editor = screen.getByRole('textbox', { name: guidedCopy('draft.label') });
    fireEvent.change(editor, { target: { value: edited } });
    await user.click(screen.getByRole('button', { name: guidedCopy('draft.next') }));
    await user.click(screen.getByTestId('demo-apply'));
    await user.click(screen.getByTestId('demo-undo'));

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(xhrOpen).not.toHaveBeenCalled();
    expect(xhrSend).not.toHaveBeenCalled();
  });

  it('keeps apply/undo in-tab and does not mutate the bundled example', async () => {
    const user = userEvent.setup();
    const seedBefore = structuredClone(createGuidedScenario());
    render(<RecordedWalkthrough scope="public" escapeHref="/" />);

    choose('left', 'include');
    choose('right', 'omit');
    const edited = 'Only this tab should keep this draft.';
    const editor = screen.getByRole('textbox', { name: guidedCopy('draft.label') });
    fireEvent.change(editor, { target: { value: edited } });
    await user.click(screen.getByRole('button', { name: guidedCopy('draft.next') }));
    await user.click(screen.getByTestId('demo-apply'));

    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', edited);
    expect(editor).toHaveValue(edited);

    await user.click(screen.getByTestId('demo-undo'));
    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', SEED_ALT_TEXT);
    expect(editor).toHaveValue(edited);

    const seedAfter = createGuidedScenario();
    expect(seedAfter).toEqual(seedBefore);
    expect(seedAfter.pressPhoto.altText).toBe(SEED_ALT_TEXT);
  });

  it('keeps js/guide sources and RecordedWalkthrough free of live/API imports', () => {
    const pluginRoot = resolve(__dirname, '../../..');
    const files = [
      ...collectSources(resolve(pluginRoot, 'js/guide')),
      resolve(pluginRoot, 'js/admin/guidedPrototype/RecordedWalkthrough.tsx'),
    ];
    const forbidden = /\/api\/|GuidedLiveDescriptionPanel|useGuidedLiveDescription/;

    for (const file of files) {
      const specs = importSpecifiers(readFileSync(file, 'utf8'));
      for (const spec of specs) {
        expect(spec, `${file} imports ${spec}`).not.toMatch(forbidden);
      }
    }
  });
});
