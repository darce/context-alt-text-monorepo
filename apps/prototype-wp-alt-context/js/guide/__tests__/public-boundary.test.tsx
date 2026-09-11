import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, extname, join, resolve } from 'node:path';

import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CASE_STUDY_URL, guidedCopy } from '../../admin/guidedPrototype/publicGuideCopy';
import { RecordedWalkthrough } from '../../admin/guidedPrototype/RecordedWalkthrough';
import { createGuidedScenario } from '../../admin/guidedPrototype/state';

const SEED_ALT_TEXT =
  'A man in a black suit and a woman in a white dress pose together, smiling, in front of a Tribeca Festival step-and-repeat backdrop.';

const choose = (position: 'left' | 'right', option: 'include' | 'omit'): void => {
  const fieldset = screen.getByTestId(`name-choice-tribeca-${position}`);
  const name =
    option === 'include'
      ? guidedCopy('names.include', { name: position === 'left' ? 'Justin Trudeau' : 'Katy Perry' })
      : guidedCopy('names.omit');
  fireEvent.click(within(fieldset).getByRole('radio', { name }));
};

const SKIP_IMPORT_EXT = new Set([
  '.css',
  '.scss',
  '.jpg',
  '.jpeg',
  '.png',
  '.gif',
  '.svg',
  '.webp',
  '.json',
  '.woff',
  '.woff2',
]);

interface ImportSpecifier {
  spec: string;
  typeOnly: boolean;
}

const importSpecifiers = (source: string): ImportSpecifier[] => {
  const specs: ImportSpecifier[] = [];
  const pattern = /(?:from|import)\s+['"]([^'"]+)['"]/g;
  for (const match of source.matchAll(pattern)) {
    const spec = match[1];
    const start = match.index ?? 0;
    const lineStart = source.lastIndexOf('\n', start - 1) + 1;
    const prefix = source.slice(lineStart, start);
    specs.push({ spec, typeOnly: /^\s*(?:import|export)\s+type\b/.test(prefix) });
  }
  return specs;
};

const resolveRelativeImport = (fromFile: string, spec: string): string | null => {
  if (!spec.startsWith('.')) {
    return null;
  }
  if (SKIP_IMPORT_EXT.has(extname(spec))) {
    return null;
  }
  const base = resolve(dirname(fromFile), spec);
  const candidates = [base, `${base}.ts`, `${base}.tsx`, join(base, 'index.ts'), join(base, 'index.tsx')];
  for (const candidate of candidates) {
    if (existsSync(candidate) && statSync(candidate).isFile()) {
      return candidate;
    }
  }
  return null;
};

const FORBIDDEN_IMPORT = /\/api\/|GuidedLiveDescriptionPanel|useGuidedLiveDescription/;
const MAX_PUBLIC_GRAPH_FILES = 256;

const collectImportGraph = (entry: string, maxFiles: number = MAX_PUBLIC_GRAPH_FILES): string[] => {
  const seen = new Set<string>();
  const queue = [entry];
  const unresolved: string[] = [];

  while (queue.length > 0) {
    const file = queue.pop();
    if (file === undefined || seen.has(file)) {
      continue;
    }
    seen.add(file);
    if (seen.size > maxFiles) {
      throw new Error(`public import graph exceeded ${maxFiles} files (unbounded walk)`);
    }
    for (const { spec, typeOnly } of importSpecifiers(readFileSync(file, 'utf8'))) {
      if (typeOnly || !spec.startsWith('.')) {
        continue;
      }
      if (SKIP_IMPORT_EXT.has(extname(spec))) {
        continue;
      }
      const resolved = resolveRelativeImport(file, spec);
      if (resolved === null) {
        unresolved.push(`${file} -> ${spec}`);
        continue;
      }
      if (!seen.has(resolved)) {
        queue.push(resolved);
      }
    }
  }

  expect(unresolved, 'unresolved relative imports in the public graph').toEqual([]);
  return [...seen];
};

const forbiddenImportHits = (files: string[]): string[] => {
  const hits: string[] = [];
  for (const file of files) {
    for (const { spec, typeOnly } of importSpecifiers(readFileSync(file, 'utf8'))) {
      if (typeOnly) {
        continue;
      }
      if (FORBIDDEN_IMPORT.test(spec)) {
        hits.push(`${file} imports ${spec}`);
      }
    }
  }
  return hits;
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

    expect(screen.getByTestId('guided-scope')).toHaveTextContent(guidedCopy('scope.public'));
    expect(screen.getByRole('heading', { level: 1, name: guidedCopy('entry.title.public') })).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('entry.intro.public'))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: guidedCopy('page.start') })).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: `${guidedCopy('entry.read_case_study')} (opens in a new window)` }),
    ).toHaveAttribute('href', CASE_STUDY_URL);

    const escape = screen.getByRole('navigation', { name: guidedCopy('nav.leave') });
    const home = within(escape).getByRole('link', {
      name: `${guidedCopy('nav.home')} (opens in a new window)`,
    });
    expect(home).toHaveAttribute('href', 'https://altcontext.com/');
    expect(home).toHaveAttribute('target', '_blank');
    expect(home).toHaveAttribute('rel', 'noreferrer');
    expect(
      within(escape).getByRole('link', { name: `${guidedCopy('nav.case_study')} (opens in a new window)` }),
    ).toHaveAttribute('href', CASE_STUDY_URL);
    expect(screen.queryByTestId('guided-live')).not.toBeInTheDocument();
  });

  it('makes no network calls across choose → edit → apply → undo', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" escapeHref="/" />);

    choose('left', 'include');
    choose('right', 'include');
    const edited = 'Public-tab festival description.';
    const editor = within(screen.getByTestId('guided-draft-field-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.field_label.public'),
    });
    fireEvent.change(editor, { target: { value: edited } });
    await user.click(screen.getByTestId('demo-apply-tribeca'));
    await user.click(screen.getByTestId('demo-undo-tribeca'));

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
    const editor = within(screen.getByTestId('guided-draft-field-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.field_label.public'),
    });
    fireEvent.change(editor, { target: { value: edited } });
    await user.click(screen.getByTestId('demo-apply-tribeca'));

    expect(screen.getByTestId('demo-applied-image-tribeca')).toHaveAttribute('alt', edited);
    expect(editor).toHaveValue(edited);

    await user.click(screen.getByTestId('demo-undo-tribeca'));
    expect(screen.getByTestId('demo-applied-image-tribeca')).toHaveAttribute('alt', SEED_ALT_TEXT);
    expect(editor).toHaveValue(edited);

    const seedAfter = createGuidedScenario();
    expect(seedAfter).toEqual(seedBefore);
    expect(seedAfter.pressPhoto.altText).toBe(SEED_ALT_TEXT);
  });

  it('shows the complete current name-choice summary separately from live feedback', () => {
    render(<RecordedWalkthrough scope="public" escapeHref="/" />);

    const summary = screen.getByTestId('guided-choice-summary');
    expect(summary).toHaveTextContent('Justin Trudeau');
    expect(summary).toHaveTextContent('Katy Perry');
    expect(summary).toHaveTextContent(guidedCopy('names.pending'));
    expect(screen.getByTestId('guided-page-feedback-status')).toHaveAttribute('aria-live', 'polite');

    choose('left', 'include');
    expect(summary).toHaveTextContent(guidedCopy('names.include', { name: 'Justin Trudeau' }));
    expect(summary).toHaveTextContent(guidedCopy('names.pending'));

    choose('right', 'omit');
    expect(summary).toHaveTextContent(guidedCopy('names.include', { name: 'Justin Trudeau' }));
    expect(summary).toHaveTextContent(guidedCopy('names.omit'));
  });

  it('keeps the full before-source attribution inside the provenance disclosure', () => {
    const { container } = render(<RecordedWalkthrough scope="public" escapeHref="/" />);
    const provenance = container.querySelector('.acx-guided-page__provenance-footer');
    expect(provenance).not.toBeNull();
    expect(provenance).toHaveTextContent(guidedCopy('context.source.summary.public'));
    expect(provenance).toHaveTextContent(guidedCopy('context.source.comparison_boundary.public'));
    expect(provenance).toHaveTextContent(guidedCopy('provenance.recorded'));
    expect(provenance?.querySelector('a[href="https://alttext.ai/"]')).toBeInTheDocument();
    const context = container.querySelector('.acx-guided-page__context');
    expect(context?.children).toHaveLength(1);
    expect(context?.querySelector('p')).toHaveTextContent(guidedCopy('context.purpose'));
    expect(context?.querySelector('details, button')).toBeNull();
  });

  it('keeps public-source narration out of admin provenance while retaining recorded attribution', () => {
    const { container } = render(<RecordedWalkthrough scope="admin" />);
    const provenance = container.querySelector('.acx-guided-page__provenance-footer');
    expect(provenance).not.toBeNull();
    expect(provenance).toHaveTextContent(guidedCopy('provenance.recorded'));
    expect(provenance).not.toHaveTextContent(guidedCopy('context.source.summary.public'));
    expect(provenance).not.toHaveTextContent(guidedCopy('context.source.comparison_boundary.public'));
    expect(provenance?.querySelector('a[href="https://alttext.ai/"]')).not.toBeInTheDocument();
    expect(container.querySelector('p.acx-guided-page__credit')).toHaveTextContent(
      createGuidedScenario().pressPhoto.credit,
    );
  });

  it('keeps public completion copy bounded for applied and kept outcomes', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" escapeHref="/" />);

    choose('left', 'include');
    choose('right', 'include');
    const editor = within(screen.getByTestId('guided-draft-field-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.field_label.public'),
    });
    await user.clear(editor);
    await user.type(editor, 'A bounded public demo edit.');
    await user.click(screen.getByTestId('demo-apply-tribeca'));
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.scope.public'));
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.next_batch.public'));
    expect(screen.getByTestId('demo-outcome')).not.toHaveTextContent(/WordPress media has been updated/i);

    await user.click(screen.getByRole('button', { name: guidedCopy('outcome.return') }));
    await user.click(
      within(screen.getByTestId('guided-description-review-tribeca')).getByRole('button', {
        name: guidedCopy('draft.keep'),
      }),
    );
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.kept'));
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.scope.public'));
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.next_batch.public'));
  });

  it('keeps reset local and clears choices, draft state, and outcome', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" escapeHref="/" />);

    choose('left', 'include');
    choose('right', 'omit');
    await user.click(screen.getByRole('button', { name: guidedCopy('page.reset') }));
    const dialog = screen.getByRole('dialog', { name: guidedCopy('reset.title') });
    await user.click(within(dialog).getByRole('button', { name: guidedCopy('reset.confirm') }));

    expect(
      within(screen.getByTestId('name-choice-tribeca-left')).getByRole('radio', { name: /^Use / }),
    ).not.toBeChecked();
    expect(
      within(screen.getByTestId('name-choice-tribeca-right')).getByRole('radio', { name: /^Use / }),
    ).not.toBeChecked();
    expect(screen.getByTestId('guided-choice-summary')).toHaveTextContent(guidedCopy('names.pending'));
    expect(screen.queryByTestId('demo-outcome')).not.toBeInTheDocument();
    expect(screen.getByTestId('guided-description-review-tribeca')).toHaveTextContent(guidedCopy('draft.blocked'));
  });

  it('does not resurrect an unsaved draft or open replacement after reset', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" escapeHref="/" />);

    const scenario = createGuidedScenario();
    choose('left', 'include');
    choose('right', 'include');
    const editor = within(screen.getByTestId('guided-draft-field-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.field_label.public'),
    });
    const staleDraft = 'Unsaved draft must not return after reset.';
    fireEvent.change(editor, { target: { value: staleDraft } });

    await user.click(screen.getByRole('button', { name: guidedCopy('page.reset') }));
    const dialog = screen.getByRole('dialog', { name: guidedCopy('reset.title') });
    await user.click(within(dialog).getByRole('button', { name: guidedCopy('reset.confirm') }));

    choose('left', 'include');
    choose('right', 'omit');

    expect(screen.queryByRole('dialog', { name: guidedCopy('names.change_title') })).not.toBeInTheDocument();
    const resetEditor = within(screen.getByTestId('guided-draft-field-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.field_label.public'),
    });
    expect(resetEditor).toHaveValue(scenario.samples.tribeca['justin-trudeau']);
    expect(resetEditor).not.toHaveValue(staleDraft);
  });

  it('walks the public entry import graph and forbids live/API imports', () => {
    const pluginRoot = resolve(__dirname, '../../..');
    const files = collectImportGraph(resolve(pluginRoot, 'js/guide/main.tsx'));

    expect(files.length).toBeLessThanOrEqual(MAX_PUBLIC_GRAPH_FILES);
    expect(files.some((file) => file.endsWith('GuidedFacesPanel.tsx'))).toBe(true);
    expect(files.some((file) => file.endsWith('GuidedDescriptionReview.tsx'))).toBe(true);
    expect(files.some((file) => file.endsWith('GuidedFaceMatchCard.tsx'))).toBe(true);
    expect(files.some((file) => file.endsWith('state.ts'))).toBe(true);
    expect(files.some((file) => file.includes('GuidedLiveDescriptionPanel'))).toBe(false);
    expect(files.some((file) => file.includes('useGuidedLiveDescription'))).toBe(false);
    expect(forbiddenImportHits(files), forbiddenImportHits(files).join('; ')).toEqual([]);
  });

  it('fails closed when a nested reachable module imports a live/API surface (canary)', () => {
    const root = mkdtempSync(join(tmpdir(), 'acx-public-boundary-'));
    try {
      const child = join(root, 'child.tsx');
      const entry = join(root, 'entry.tsx');
      writeFileSync(
        child,
        "import { GuidedLiveDescriptionPanel } from 'GuidedLiveDescriptionPanel';\nexport const leak = GuidedLiveDescriptionPanel;\n",
      );
      writeFileSync(entry, "import { leak } from './child';\nexport const root = leak;\n");
      const files = collectImportGraph(entry);
      expect(files.some((file) => file.endsWith('child.tsx'))).toBe(true);
      const hits = forbiddenImportHits(files);
      expect(hits.length, 'canary must fail when a descendant imports a live/API surface').toBeGreaterThan(0);
      expect(() => collectImportGraph(entry, 1)).toThrow(/exceeded 1/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
