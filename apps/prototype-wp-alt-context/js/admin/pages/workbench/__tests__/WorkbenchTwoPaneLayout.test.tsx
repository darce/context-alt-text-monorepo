import type { ReactNode } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import { DEFAULT_STACK_BELOW_PX, WorkbenchTwoPaneLayout, type WorkbenchPanesState } from '../WorkbenchTwoPaneLayout';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, _plural: string, count: number) => (count === 1 ? single : _plural),
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

type MatchMediaListener = (event: MediaQueryListEvent) => void;

const installMatchMedia = (
  matches: boolean,
): {
  setMatches: (next: boolean) => void;
  mediaQuery: MediaQueryList;
} => {
  const listeners = new Set<MatchMediaListener>();
  let current = matches;

  const mediaQuery = {
    get matches() {
      return current;
    },
    media: '',
    onchange: null,
    addEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
      if (typeof listener === 'function') {
        listeners.add(listener);
      }
    },
    removeEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
      if (typeof listener === 'function') {
        listeners.delete(listener);
      }
    },
    addListener: (listener: MatchMediaListener) => {
      listeners.add(listener);
    },
    removeListener: (listener: MatchMediaListener) => {
      listeners.delete(listener);
    },
    dispatchEvent: () => true,
  } as MediaQueryList;

  window.matchMedia = vi.fn().mockImplementation(() => mediaQuery);

  return {
    setMatches: (next: boolean) => {
      current = next;
      const event = { matches: next } as MediaQueryListEvent;
      listeners.forEach((listener) => listener(event));
    },
    mediaQuery,
  };
};

const renderLayout = (
  overrides: Partial<{
    control: ReactNode;
    library: ReactNode;
    panes: WorkbenchPanesState;
    onPanesChange: (next: WorkbenchPanesState) => void;
    stackBelowPx: number;
  }> = {},
) => {
  const onPanesChange: Mock<(next: WorkbenchPanesState) => void> =
    (overrides.onPanesChange as Mock<(next: WorkbenchPanesState) => void> | undefined) ??
    vi.fn<(next: WorkbenchPanesState) => void>();
  const result = render(
    <WorkbenchTwoPaneLayout
      control={overrides.control === undefined ? <div>Control body</div> : overrides.control}
      library={overrides.library === undefined ? <div>Library body</div> : overrides.library}
      panes={overrides.panes ?? 'both'}
      onPanesChange={onPanesChange}
      stackBelowPx={overrides.stackBelowPx}
    />,
  );
  return { ...result, onPanesChange };
};

describe('WorkbenchTwoPaneLayout', () => {
  beforeEach(() => {
    installMatchMedia(false);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders both host regions and the splitter from injected control/library nodes', () => {
    renderLayout();

    const control = screen.getByTestId('workbench-two-pane-control');
    const library = screen.getByTestId('workbench-two-pane-library');
    const splitter = screen.getByRole('separator');

    expect(control).toBeTruthy();
    expect(library).toBeTruthy();
    expect(splitter).toBeTruthy();
    expect(within(control).getByText('Control body')).toBeTruthy();
    expect(within(library).getByText('Library body')).toBeTruthy();
  });

  it('renders designed zero-states when slots are empty [LAY-10/NAV-08]', () => {
    renderLayout({ control: null, library: null });

    const control = screen.getByTestId('workbench-two-pane-control');
    const library = screen.getByTestId('workbench-two-pane-library');

    expect(control).toBeTruthy();
    expect(library).toBeTruthy();
    expect(within(control).getByRole('heading', { name: 'Control' })).toBeTruthy();
    expect(within(library).getByRole('heading', { name: 'Library' })).toBeTruthy();
    expect(within(control).getByRole('status')).toBeTruthy();
    expect(within(library).getByRole('status')).toBeTruthy();
    // L2V-04: pin exact zero-state copy (not merely non-empty textContent).
    expect(
      within(control).getByText(
        'Recognition and cluster controls will appear here. Run recognition when media is ready.',
      ),
    ).toBeTruthy();
    expect(
      within(library).getByText(
        'Media library will appear here. Select or filter media to caption and describe.',
      ),
    ).toBeTruthy();
  });

  it('moves focus to the splitter when a pane collapses under keyboard focus [L2V-02]', async () => {
    const user = userEvent.setup();
    const onPanesChange = vi.fn<(next: WorkbenchPanesState) => void>();
    const layoutFor = (panes: WorkbenchPanesState) => (
      <WorkbenchTwoPaneLayout
        control={
          <button type="button" data-testid="control-focus-target">
            Control action
          </button>
        }
        library={<div>Library body</div>}
        panes={panes}
        onPanesChange={onPanesChange}
      />
    );
    const { rerender } = render(layoutFor('both'));

    const focusTarget = screen.getByTestId('control-focus-target');
    focusTarget.focus();
    expect(document.activeElement).toBe(focusTarget);

    // Collapse control while focus is still inside the control pane.
    rerender(layoutFor('control-collapsed'));

    await vi.waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole('separator'));
    });

    // Keyboard collapse cycle still routes through onPanesChange.
    screen.getByRole('separator').focus();
    await user.keyboard('{Enter}');
    expect(onPanesChange).toHaveBeenLastCalledWith('library-collapsed');
  });

  it('treats an array of empty children as an empty slot [isSlotEmpty array branch]', () => {
    renderLayout({ control: [null, false, ''], library: [null, undefined, true] });

    const control = screen.getByTestId('workbench-two-pane-control');
    const library = screen.getByTestId('workbench-two-pane-library');

    expect(control.getAttribute('data-empty')).toBe('true');
    expect(library.getAttribute('data-empty')).toBe('true');
    expect(within(control).getByRole('status')).toBeTruthy();
    expect(within(library).getByRole('status')).toBeTruthy();
  });

  it('treats an array with one real child as a non-empty slot [isSlotEmpty array branch]', () => {
    renderLayout({
      control: [null, <div key="c">Control from array</div>],
      library: [false, '', <span key="l">Library from array</span>],
    });

    const control = screen.getByTestId('workbench-two-pane-control');
    const library = screen.getByTestId('workbench-two-pane-library');

    expect(control.getAttribute('data-empty')).toBe('false');
    expect(library.getAttribute('data-empty')).toBe('false');
    expect(within(control).queryByRole('status')).toBeNull();
    expect(within(library).queryByRole('status')).toBeNull();
    expect(within(control).getByText('Control from array')).toBeTruthy();
    expect(within(library).getByText('Library from array')).toBeTruthy();
  });

  it('marks the library host as the dominant region and sizes the split 35/65 [LAY-01]', () => {
    renderLayout();

    const library = screen.getByTestId('workbench-two-pane-library');
    const control = screen.getByTestId('workbench-two-pane-control');
    const splitter = screen.getByRole('separator');

    expect(library.getAttribute('data-dominant')).toBe('true');
    expect(control.getAttribute('data-dominant')).toBe('false');
    expect(library.className).toMatch(/two-pane-library/);

    // Dominance is real geometry, not just an attribute: library gets the larger basis.
    expect(control.style.flexBasis).toBe('35%');
    expect(library.style.flexBasis).toBe('65%');
    expect(splitter.getAttribute('aria-valuenow')).toBe('35');
  });

  it('exposes an accessible separator that resizes and collapses deterministically via keyboard [A11Y-04/TEST-15]', async () => {
    const user = userEvent.setup();
    const onPanesChange = vi.fn<(next: WorkbenchPanesState) => void>();
    const layoutFor = (panes: WorkbenchPanesState) => (
      <WorkbenchTwoPaneLayout
        control={<div>Control body</div>}
        library={<div>Library body</div>}
        panes={panes}
        onPanesChange={onPanesChange}
      />
    );
    const { rerender } = render(layoutFor('both'));

    const splitter = screen.getByRole('separator');
    // The accessible name states the action and its targets, not just any non-empty text.
    const label = splitter.getAttribute('aria-label') ?? '';
    expect(label).toMatch(/resize/i);
    expect(label).toMatch(/control|library/i);
    expect(splitter.getAttribute('tabindex')).toBe('0');

    // Default split ratio is surfaced as aria-valuenow=35 [DEFAULT_SPLIT_RATIO/LAY-01].
    expect(splitter.getAttribute('aria-valuenow')).toBe('35');
    const min = Number(splitter.getAttribute('aria-valuemin'));
    const max = Number(splitter.getAttribute('aria-valuemax'));

    splitter.focus();
    await user.keyboard('{ArrowRight}');
    expect(Number(splitter.getAttribute('aria-valuenow'))).toBe(40);
    await user.keyboard('{ArrowLeft}');
    expect(Number(splitter.getAttribute('aria-valuenow'))).toBe(35);

    await user.keyboard('{Home}');
    expect(Number(splitter.getAttribute('aria-valuenow'))).toBe(min);
    await user.keyboard('{End}');
    expect(Number(splitter.getAttribute('aria-valuenow'))).toBe(max);

    // Enter drives a deterministic collapse cycle: both -> control -> library -> both.
    await user.keyboard('{Enter}');
    expect(onPanesChange).toHaveBeenLastCalledWith('control-collapsed');

    rerender(layoutFor('control-collapsed'));
    screen.getByRole('separator').focus();
    await user.keyboard('{Enter}');
    expect(onPanesChange).toHaveBeenLastCalledWith('library-collapsed');

    rerender(layoutFor('library-collapsed'));
    screen.getByRole('separator').focus();
    await user.keyboard('{Enter}');
    expect(onPanesChange).toHaveBeenLastCalledWith('both');
  });

  it('at the stack breakpoint puts library host first and toggles sections via keyboard [A11Y-08]', async () => {
    const user = userEvent.setup();
    installMatchMedia(true);
    const { onPanesChange } = renderLayout({ stackBelowPx: DEFAULT_STACK_BELOW_PX });

    // Stacking is driven off the 320px media query, not untestable layout geometry.
    expect(window.matchMedia).toHaveBeenCalledWith(`(max-width: ${DEFAULT_STACK_BELOW_PX}px)`);

    const root = screen.getByTestId('workbench-two-pane');
    expect(root.getAttribute('data-layout')).toBe('stacked');

    const children = Array.from(root.children) as HTMLElement[];
    const firstHost = children.find(
      (el) =>
        el.getAttribute('data-testid') === 'workbench-two-pane-library' ||
        el.getAttribute('data-testid') === 'workbench-two-pane-control',
    );
    expect(firstHost?.getAttribute('data-testid')).toBe('workbench-two-pane-library');

    const splitter = screen.getByRole('separator');
    expect(splitter.getAttribute('data-mode')).toBe('section-toggle');
    const label = splitter.getAttribute('aria-label') ?? '';
    expect(label.toLowerCase()).toMatch(/toggle|section|show|hide|expand|collapse/);

    // A section toggle has no value range and collapses via keyboard [A11Y-04].
    expect(splitter.getAttribute('aria-valuenow')).toBeNull();
    expect(splitter.getAttribute('aria-valuemin')).toBeNull();
    splitter.focus();
    await user.keyboard('{Enter}');
    expect(onPanesChange).toHaveBeenLastCalledWith('control-collapsed');
  });

  it('side-by-side above the breakpoint keeps control before library in DOM', () => {
    installMatchMedia(false);
    renderLayout();

    const root = screen.getByTestId('workbench-two-pane');
    expect(root.getAttribute('data-layout')).toBe('side-by-side');

    const children = Array.from(root.children) as HTMLElement[];
    const hosts = children.filter((el) =>
      ['workbench-two-pane-control', 'workbench-two-pane-library'].includes(el.getAttribute('data-testid') ?? ''),
    );
    expect(hosts[0]?.getAttribute('data-testid')).toBe('workbench-two-pane-control');
    expect(hosts[1]?.getAttribute('data-testid')).toBe('workbench-two-pane-library');
  });

  it("panes='control-collapsed' hides control and expands library", () => {
    renderLayout({ panes: 'control-collapsed' });

    const control = screen.getByTestId('workbench-two-pane-control');
    const library = screen.getByTestId('workbench-two-pane-library');
    const root = screen.getByTestId('workbench-two-pane');

    expect(root.getAttribute('data-panes')).toBe('control-collapsed');
    expect(control.getAttribute('data-collapsed')).toBe('true');
    expect(control.getAttribute('hidden')).not.toBeNull();
    expect(library.getAttribute('data-collapsed')).toBe('false');
    expect(library.getAttribute('hidden')).toBeNull();
  });

  it("panes='library-collapsed' hides library and expands control", () => {
    renderLayout({ panes: 'library-collapsed' });

    const control = screen.getByTestId('workbench-two-pane-control');
    const library = screen.getByTestId('workbench-two-pane-library');

    expect(library.getAttribute('data-collapsed')).toBe('true');
    expect(library.getAttribute('hidden')).not.toBeNull();
    expect(control.getAttribute('data-collapsed')).toBe('false');
    expect(control.getAttribute('hidden')).toBeNull();
  });

  it("panes='both' shows both regions", () => {
    renderLayout({ panes: 'both' });

    const control = screen.getByTestId('workbench-two-pane-control');
    const library = screen.getByTestId('workbench-two-pane-library');

    expect(control.getAttribute('data-collapsed')).toBe('false');
    expect(library.getAttribute('data-collapsed')).toBe('false');
    expect(control.getAttribute('hidden')).toBeNull();
    expect(library.getAttribute('hidden')).toBeNull();
  });

  it('pointer drag adjusts the split ratio without relying on layout geometry', () => {
    renderLayout();

    const splitter = screen.getByRole('separator');
    const before = Number(splitter.getAttribute('aria-valuenow'));

    fireEvent.pointerDown(splitter, { pointerId: 1, clientX: 100, clientY: 0 });
    fireEvent.pointerMove(splitter, { pointerId: 1, clientX: 140, clientY: 0, movementX: 40 });
    fireEvent.pointerUp(splitter, { pointerId: 1, clientX: 140, clientY: 0 });

    const after = Number(splitter.getAttribute('aria-valuenow'));
    expect(after).not.toBe(before);
  });
});
