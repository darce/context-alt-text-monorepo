import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, extname, join, resolve } from 'node:path';

import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CASE_STUDY_URL, RECORDING_URL, guidedCopy } from '../../admin/guidedPrototype/publicGuideCopy';
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

const SKIP_IMPORT_EXT = new Set([
  '.css',
  '.scss',
  '.jpg',
  '.jpeg',
  '.png',
  '.gif',
  '.svg',
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

    expect(screen.getByTestId('guided-scope')).toHaveTextContent(PUBLIC_SCOPE);
    expect(screen.getByRole('button', { name: guidedCopy('page.start') })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: `${guidedCopy('entry.watch')} (opens in a new window)` })).toHaveAttribute(
      'href',
      RECORDING_URL,
    );
    expect(
      screen.getByRole('link', { name: `${guidedCopy('entry.read_case_study')} (opens in a new window)` }),
    ).toHaveAttribute('href', CASE_STUDY_URL);

    const escape = screen.getByRole('navigation', { name: guidedCopy('nav.leave') });
    expect(within(escape).getByRole('link', { name: guidedCopy('nav.home') })).toHaveAttribute(
      'href',
      'https://demo.example/',
    );
    expect(
      within(escape).getByRole('link', { name: `${guidedCopy('nav.case_study')} (opens in a new window)` }),
    ).toHaveAttribute('href', CASE_STUDY_URL);
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
