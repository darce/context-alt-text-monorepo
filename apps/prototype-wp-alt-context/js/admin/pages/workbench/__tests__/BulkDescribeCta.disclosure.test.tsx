import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { DescribeRunProgress } from '../../../hooks/useDescribeRunProgress';
import { BulkDescribeCta } from '../MediaSelection';
import { RECOGNITION_POLICY } from '../mediaFooterCtaState';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

vi.mock('../BulkDescribeReviewLink', () => ({
  BulkDescribeReviewLink: () => null,
}));

const idleProgress = {
  status: null,
  run: null,
  isTerminal: false,
  isError: false,
  isPolling: false,
  etaSeconds: null,
  progressFraction: 0,
  retry: vi.fn(),
} as unknown as DescribeRunProgress;

/**
 * WBUX6-W3-L1-03: a FACTORY, not a shared module-level object. One `vi.fn()` reused
 * across every case makes call-count assertions accumulate silently — a false green
 * waiting to happen [TEST-15 lexicons/engineering.md:396].
 */
const baseProps = () => ({
  selectedCount: 2,
  isSubmitting: false,
  isCancelling: false,
  isRunning: false,
  runId: null as string | null,
  progress: idleProgress,
  isPanelVisible: false,
  errorMessage: null as string | null,
  isIdentifying: false,
  recognitionPolicy: RECOGNITION_POLICY.LOADING,
  onSubmit: vi.fn(),
  onCancel: vi.fn(),
  onDismiss: vi.fn(),
  onRetryPolling: vi.fn(),
});

const describedTargets = (button: HTMLElement): HTMLElement[] => {
  const ids = (button.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
  return ids
    .map((id) => document.getElementById(id))
    .filter((node): node is HTMLElement => node !== null);
};

describe('BulkDescribeCta recognition disclosure (HAI-04 / HAI-05 / RLSE-04)', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('labels the primary with the selected count', () => {
    render(<BulkDescribeCta {...baseProps()} selectedCount={3} recognitionPolicy={RECOGNITION_POLICY.ON} />);

    expect(screen.getByRole('button', { name: 'Describe 3 selected' })).toBeInTheDocument();
  });

  it('discloses ON wording, credits, and a Settings off-ramp when recognition is known on', () => {
    render(<BulkDescribeCta {...baseProps()} selectedCount={12} recognitionPolicy={RECOGNITION_POLICY.ON} />);

    const disclosure = screen.getByText(/Identifies people first \(AI\)/);
    expect(disclosure).toHaveTextContent('Identifies people first (AI) · ~12 credits · Turn off in Settings');
    const settings = screen.getByRole('link', { name: 'Settings' });
    expect(settings).toHaveAttribute('href', '#/settings');
    expect(disclosure).toContainElement(settings);
  });

  it('keeps GPU cost disclosure separate with a GPU controls link and one recognition Settings link', () => {
    render(<BulkDescribeCta {...baseProps()} recognitionPolicy={RECOGNITION_POLICY.ON} />);

    const disclosure = screen.getByTestId('acx-bulk-describe-gpu-cost');
    const controls = screen.getByRole('link', { name: 'GPU controls' });
    expect(disclosure).toHaveTextContent('Describe may start the GPU and require warm-up.');
    expect(disclosure).toHaveTextContent('GPU infrastructure charges are separate from description credits.');
    expect(disclosure).toContainElement(controls);
    expect(controls).toHaveAttribute('href', '#/settings');
    expect(screen.getAllByRole('link', { name: 'Settings' })).toHaveLength(1);
    expect(describedTargets(screen.getByRole('button', { name: 'Describe 2 selected' })))
      .not.toContain(disclosure);
    expect(disclosure.closest('[aria-live], [role="status"]')).toBeNull();
  });

  it('discloses OFF wording and credits without a Settings link when recognition is known off', () => {
    render(<BulkDescribeCta {...baseProps()} selectedCount={4} recognitionPolicy={RECOGNITION_POLICY.OFF} />);

    expect(
      screen.getByText('People are not identified (recognition off) · ~4 credits'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument();
  });

  it('ties the primary to the disclosure via aria-describedby', () => {
    render(<BulkDescribeCta {...baseProps()} recognitionPolicy={RECOGNITION_POLICY.ON} />);

    const button = screen.getByRole('button', { name: 'Describe 2 selected' });
    const targets = describedTargets(button);
    expect(targets.length).toBeGreaterThan(0);
    expect(targets.some((node) => node.textContent?.includes('Identifies people first (AI)'))).toBe(
      true,
    );
  });

  it('does not claim recognition is off while the policy is unknown', () => {
    render(<BulkDescribeCta {...baseProps()} selectedCount={2} />);

    expect(screen.queryByText(/recognition off/)).not.toBeInTheDocument();
    expect(screen.getByText('Checking recognition settings…')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument();
  });
});

/**
 * WBUX6-MRG-05 — the settings probe FAILED. `retry: false` makes that terminal, so
 * "checking…" would be a lie told forever. UNAVAILABLE is a designed degraded state
 * [RLSE-04 lexicons/engineering.md:695][A11Y-24 lexicons/accessibility.md:154]: the
 * disclosure states plainly that people will not be identified, and the primary
 * stays actionable [COST-10 lexicons/ml-systems.md:553].
 */
describe('BulkDescribeCta recognition disclosure — settings probe failed', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('names the degradation instead of claiming it is still checking', () => {
    render(
      <BulkDescribeCta
        {...baseProps()}
        selectedCount={7}
        recognitionPolicy={RECOGNITION_POLICY.UNAVAILABLE}
      />,
    );

    // TWO surfaces carry the copy: the describing node and the announcing region
    // (WBUX6-W4-B-02). Exactly two — a third would mean a duplicated surface.
    expect(
      screen.getAllByText(
        /Recognition settings unavailable — describing without identifying people · ~7 credits/,
      ),
    ).toHaveLength(2);
    // The unbounded-wait wording must be gone; that is the whole regression.
    expect(screen.queryByText(/Checking recognition settings/)).not.toBeInTheDocument();
    // And it must not silently pose as a deliberate opt-out either (HAI-05).
    expect(screen.queryByText(/recognition off/)).not.toBeInTheDocument();
  });

  it('keeps the degraded disclosure wired to the primary via aria-describedby', () => {
    render(<BulkDescribeCta {...baseProps()} recognitionPolicy={RECOGNITION_POLICY.UNAVAILABLE} />);

    const button = screen.getByRole('button', { name: 'Describe 2 selected' });
    expect(
      describedTargets(button).some((node) =>
        node.textContent?.includes('Recognition settings unavailable'),
      ),
    ).toBe(true);
  });
});

/**
 * WBUX6-W4-B-02 — one surface DESCRIBES, a different surface ANNOUNCES [A11Y-21
 * lexicons/accessibility.md]. The aria-describedby target is only reachable on focus,
 * so an operator whose focus is elsewhere when the settings probe settles would never
 * learn the run just silently stopped identifying people. Pinned in
 * docs/ux-maps/workbench-2pane.uxmap.json (z-lib-actions).
 */
describe('degraded-recognition notice: describe and announce are different nodes', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  const degradedNodes = () => {
    const button = screen.getByRole('button', { name: /^Describe/ });
    const describedIds = (button.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
    const describing = describedTargets(button).find((node) =>
      node.textContent?.includes('Recognition settings unavailable'),
    );
    const announcing = screen
      .getAllByRole('status')
      .filter((node) => node.textContent?.includes('Recognition settings unavailable'));
    return { button, describedIds, describing, announcing };
  };

  it('mirrors the copy into a polite live region that is NOT the describedby target', () => {
    render(
      <BulkDescribeCta
        {...baseProps()}
        selectedCount={7}
        recognitionPolicy={RECOGNITION_POLICY.UNAVAILABLE}
      />,
    );

    const { describedIds, describing, announcing } = degradedNodes();
    expect(describing).toBeDefined();
    expect(announcing).toHaveLength(1);
    const live = announcing[0];

    // The two jobs live on two different nodes — this is the whole contract.
    expect(live).not.toBe(describing);
    expect(live).toHaveAttribute('aria-live', 'polite');
    // The announcing node carries no id, so it CANNOT be an aria-describedby target.
    expect(live.id).toBe('');
    expect(describedIds).not.toContain(live.id);
    // ...and the describing node is not itself a live region (no double duty).
    expect(describing).not.toHaveAttribute('aria-live');
    expect(describing).not.toHaveAttribute('role');
  });

  it('mirrors the SAME string, so the two surfaces cannot drift apart', () => {
    render(
      <BulkDescribeCta
        {...baseProps()}
        selectedCount={7}
        recognitionPolicy={RECOGNITION_POLICY.UNAVAILABLE}
      />,
    );

    const { describing, announcing } = degradedNodes();
    expect(describing?.textContent?.trim()).toBe(announcing[0].textContent?.trim());
    expect(announcing[0].textContent?.trim()).toBe(
      'Recognition settings unavailable — describing without identifying people · ~7 credits',
    );
  });

  it('announces nothing in the resolved states — only the degradation is announced', () => {
    for (const policy of [
      RECOGNITION_POLICY.ON,
      RECOGNITION_POLICY.OFF,
      RECOGNITION_POLICY.LOADING,
    ]) {
      const { unmount } = render(<BulkDescribeCta {...baseProps()} recognitionPolicy={policy} />);
      expect(
        screen
          .getAllByRole('status')
          .some((node) => node.textContent?.includes('Recognition settings unavailable')),
      ).toBe(false);
      // "Checking recognition settings…" must stay a DESCRIPTION, never an announcement.
      expect(
        screen
          .getAllByRole('status')
          .some((node) => node.textContent?.includes('Checking recognition settings')),
      ).toBe(false);
      unmount();
    }
  });
});
