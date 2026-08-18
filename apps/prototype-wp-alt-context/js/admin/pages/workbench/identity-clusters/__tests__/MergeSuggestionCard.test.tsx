import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { MergeSuggestionCard } from '../MergeSuggestionCard';
import type { PendingMergeSuggestion } from '../../../../api/recognition/types';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

const FACE_BBOX = { x: 10, y: 20, width: 80, height: 90 };

const baseSuggestion: PendingMergeSuggestion = {
  id: 'merge-1',
  cluster_a_id: 'cluster-a',
  cluster_b_id: 'cluster-b',
  similarity: 0.87,
  status: 'pending',
  cluster_a_label: 'Alex',
  cluster_b_label: 'Jordan',
  cluster_a_identity_count: 3,
  cluster_b_identity_count: 4,
};

const withFaces = (overrides: Partial<PendingMergeSuggestion> = {}): PendingMergeSuggestion => ({
  ...baseSuggestion,
  cluster_a_representative_media_url: 'http://example.test/a.jpg',
  cluster_a_representative_bbox: FACE_BBOX,
  cluster_b_representative_media_url: 'http://example.test/b.jpg',
  cluster_b_representative_bbox: FACE_BBOX,
  ...overrides,
});

describe('MergeSuggestionCard', () => {


  it('renders labels and similarity for merge review', () => {
    render(<MergeSuggestionCard suggestion={baseSuggestion} onAccept={vi.fn()} onReject={vi.fn()} isPending={false} />);

    expect(screen.getByText('Are these the same person?')).toBeInTheDocument();
    expect(screen.getByText('87% match')).toBeInTheDocument();
    expect(screen.getByText('Alex (3)')).toBeInTheDocument();
    expect(screen.getByText('Jordan (4)')).toBeInTheDocument();
  });

  it('disables actions while pending and calls handlers when active', async () => {
    const onAccept = vi.fn();
    const onReject = vi.fn();

    const { rerender } = render(
      <MergeSuggestionCard suggestion={baseSuggestion} onAccept={onAccept} onReject={onReject} isPending={true} />,
    );

    expect(screen.getByRole('button', { name: 'Yes' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'No' })).toBeDisabled();

    rerender(
      <MergeSuggestionCard suggestion={baseSuggestion} onAccept={onAccept} onReject={onReject} isPending={false} />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Yes' }));
    await user.click(screen.getByRole('button', { name: 'No' }));

    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  // FIX-1 / A11Y-02 / HAI-01: auto cluster-* must not name a face on screen or in alt.
  it('gates auto cluster-* labels to Unnamed face group / Detected face alt', () => {
    const { container } = render(
      <MergeSuggestionCard
        suggestion={withFaces({
          cluster_a_label: 'cluster-7',
          cluster_b_label: 'cluster-9',
          cluster_a_identity_count: 2,
          cluster_b_identity_count: 5,
        })}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
      />,
    );

    expect(container.textContent).not.toContain('cluster-7');
    expect(container.textContent).not.toContain('cluster-9');
    expect(screen.queryByAltText('cluster-7')).toBeNull();
    expect(screen.queryByAltText('cluster-9')).toBeNull();
    const alts = screen.getAllByRole('img').map((img) => img.getAttribute('alt') ?? '');
    expect(alts).toHaveLength(2);
    expect(alts.every((alt) => alt.includes('Detected face'))).toBe(true);
    expect(screen.getByText('Unnamed face group (2)')).toBeInTheDocument();
    expect(screen.getByText('Unnamed face group (5)')).toBeInTheDocument();
  });

  // Discriminates isHumanLabeledTarget (trims) from isMeaningfulMergeLabel (no trim).
  it('gates whitespace-padded cluster-* the same as bare auto-labels', () => {
    const { container } = render(
      <MergeSuggestionCard
        suggestion={withFaces({
          cluster_a_label: '  cluster-7',
          cluster_b_label: 'cluster-9',
          cluster_a_identity_count: 3,
          cluster_b_identity_count: 4,
        })}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
      />,
    );

    expect(container.textContent).not.toContain('cluster-7');
    expect(screen.queryByAltText('cluster-7')).toBeNull();
    expect(screen.queryByAltText('  cluster-7')).toBeNull();
    const alts = screen.getAllByRole('img').map((img) => img.getAttribute('alt') ?? '');
    expect(alts).toHaveLength(2);
    expect(alts.every((alt) => alt.includes('Detected face'))).toBe(true);
    expect(screen.getByText('Unnamed face group (3)')).toBeInTheDocument();
  });

  it('keeps human labels as visible text and crop alt with identity count', () => {
    render(
      <MergeSuggestionCard
        suggestion={withFaces({
          cluster_a_label: 'Ada Lovelace',
          cluster_b_label: 'Jordan',
          cluster_a_identity_count: 3,
          cluster_b_identity_count: 4,
        })}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
      />,
    );

    expect(screen.getByText('Ada Lovelace (3)')).toBeInTheDocument();
    expect(screen.getByAltText('Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByText('Jordan (4)')).toBeInTheDocument();
    expect(screen.getByAltText('Jordan')).toBeInTheDocument();
  });

  // BR-28: case / underscore variants must not pass the display gate.
  it('gates Cluster- and cluster_ auto-labels to Unnamed face group / Detected face alt', () => {
    const { container } = render(
      <MergeSuggestionCard
        suggestion={withFaces({
          cluster_a_label: 'Cluster-abcdef12',
          cluster_b_label: 'cluster_abcdef12',
          cluster_a_identity_count: 2,
          cluster_b_identity_count: 5,
        })}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
      />,
    );

    expect(container.textContent).not.toContain('Cluster-abcdef12');
    expect(container.textContent).not.toContain('cluster_abcdef12');
    expect(screen.queryByAltText('Cluster-abcdef12')).toBeNull();
    expect(screen.queryByAltText('cluster_abcdef12')).toBeNull();
    expect(screen.getByText('Unnamed face group (2)')).toBeInTheDocument();
    expect(screen.getByText('Unnamed face group (5)')).toBeInTheDocument();
    // Alts stay gated (exact side wording asserted in BR-30).
    const alts = screen.getAllByRole('img').map((img) => img.getAttribute('alt') ?? '');
    expect(alts).toHaveLength(2);
    expect(alts.every((alt) => alt.includes('Detected face'))).toBe(true);
    expect(alts.every((alt) => !/cluster[-_]/i.test(alt))).toBe(true);
  });

  // BR-29: lightbox callback must carry the gated alt, never a raw cluster-* string.
  it('passes gated alt to onOpenOriginal lightbox payload, never cluster-*', async () => {
    const onOpenOriginal = vi.fn();
    const user = userEvent.setup();

    render(
      <MergeSuggestionCard
        suggestion={withFaces({
          cluster_a_label: 'cluster-7',
          cluster_b_label: 'cluster-9',
          cluster_a_identity_count: 2,
          cluster_b_identity_count: 5,
        })}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onOpenOriginal={onOpenOriginal}
        isPending={false}
      />,
    );

    const faceControls = screen.getAllByRole('button', { name: /View original photo/i });
    expect(faceControls.length).toBeGreaterThanOrEqual(1);
    await user.click(faceControls[0]);

    expect(onOpenOriginal).toHaveBeenCalledTimes(1);
    const payload = onOpenOriginal.mock.calls[0][0] as { label: string };
    expect(payload.label).toMatch(/Detected face/i);
    expect(payload.label).not.toMatch(/cluster[-_]/i);
    expect(payload.label).not.toContain('cluster-7');
  });

  it('passes human label to onOpenOriginal lightbox payload', async () => {
    const onOpenOriginal = vi.fn();
    const user = userEvent.setup();

    render(
      <MergeSuggestionCard
        suggestion={withFaces({
          cluster_a_label: 'Jane Doe',
          cluster_b_label: 'Jordan',
        })}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onOpenOriginal={onOpenOriginal}
        isPending={false}
      />,
    );

    const faceControls = screen.getAllByRole('button', { name: /View original photo/i });
    await user.click(faceControls[0]);
    expect(onOpenOriginal).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'Jane Doe' }),
    );
  });

  // BR-30: co-rendered auto sides and cards must not share identical accessible names.
  it('differentiates accessible names for auto-label face sides and controls', () => {
    render(
      <MergeSuggestionCard
        suggestion={withFaces({
          cluster_a_label: 'cluster-7',
          cluster_b_label: 'cluster-9',
          cluster_a_identity_count: 2,
          cluster_b_identity_count: 5,
        })}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onOpenOriginal={vi.fn()}
        isPending={false}
      />,
    );

    // Visible fallback text stays the honest Unnamed face group wording.
    expect(screen.getByText('Unnamed face group (2)')).toBeInTheDocument();
    expect(screen.getByText('Unnamed face group (5)')).toBeInTheDocument();

    const alts = screen.getAllByRole('img').map((img) => img.getAttribute('alt') ?? '');
    expect(alts).toHaveLength(2);
    expect(alts[0]).not.toBe(alts[1]);
    expect(alts.every((alt) => alt.includes('Detected face'))).toBe(true);

    const faceControls = screen.getAllByRole('button', { name: /View original photo/i });
    expect(faceControls).toHaveLength(2);
    const controlNames = faceControls.map((btn) => btn.getAttribute('aria-label') ?? btn.textContent ?? '');
    expect(controlNames[0]).not.toBe(controlNames[1]);
    expect(controlNames.every((name) => name.includes('View original photo'))).toBe(true);
  });

  it('differentiates Yes/No accessible naming across co-rendered merge cards', () => {
    render(
      <>
        <MergeSuggestionCard
          suggestion={withFaces({
            id: 'merge-card-a',
            cluster_a_label: 'cluster-7',
            cluster_b_label: 'cluster-9',
            cluster_a_identity_count: 2,
            cluster_b_identity_count: 5,
            similarity: 0.87,
          })}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          isPending={false}
        />
        <MergeSuggestionCard
          suggestion={withFaces({
            id: 'merge-card-b',
            cluster_a_label: 'cluster-11',
            cluster_b_label: 'cluster-13',
            cluster_a_identity_count: 3,
            cluster_b_identity_count: 4,
            similarity: 0.91,
          })}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          isPending={false}
        />
      </>,
    );

    const cards = screen.getAllByTestId('acx-review-card');
    expect(cards).toHaveLength(2);

    // Label-in-name: visible Yes/No remain the accessible name.
    const yesA = within(cards[0]).getByRole('button', { name: 'Yes' });
    const yesB = within(cards[1]).getByRole('button', { name: 'Yes' });
    const noA = within(cards[0]).getByRole('button', { name: 'No' });
    const noB = within(cards[1]).getByRole('button', { name: 'No' });

    const descriptionOf = (el: HTMLElement): string =>
      (el.getAttribute('aria-describedby') ?? '')
        .split(/\s+/)
        .filter(Boolean)
        .map((id) => document.getElementById(id)?.textContent ?? '')
        .join(' ');

    const yesDescA = descriptionOf(yesA);
    const yesDescB = descriptionOf(yesB);
    const noDescA = descriptionOf(noA);
    const noDescB = descriptionOf(noB);

    // Per-card context (question + side differentiators + match) distinguishes pairs.
    expect(yesDescA).toMatch(/Are these the same person\?/);
    expect(yesDescB).toMatch(/Are these the same person\?/);
    expect(yesDescA).toMatch(/first group/);
    expect(yesDescB).toMatch(/first group/);
    expect(yesDescA).not.toBe(yesDescB);
    expect(noDescA).not.toBe(noDescB);
    expect(cards[0].getAttribute('aria-describedby')).not.toBe(
      cards[1].getAttribute('aria-describedby'),
    );
    expect(cards[0]).toHaveAccessibleDescription(/87% match/);
    expect(cards[1]).toHaveAccessibleDescription(/91% match/);
    // Must not leak raw auto-label ids into accessible naming context.
    expect(`${yesDescA} ${yesDescB} ${noDescA} ${noDescB}`).not.toMatch(/cluster[-_]\w/i);
  });

  // BR-35: per-card ordinal props disambiguate co-rendered merge cards with equal match%.
  it('BR-35: queue ordinal makes co-rendered equal-match cards unique in group/Yes/face accnames', () => {
    render(
      <>
        <MergeSuggestionCard
          suggestion={withFaces({
            id: 'merge-ord-a',
            cluster_a_label: 'cluster-7',
            cluster_b_label: 'cluster-9',
            cluster_a_identity_count: 2,
            cluster_b_identity_count: 5,
            similarity: 0.87,
          })}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          onOpenOriginal={vi.fn()}
          isPending={false}
          queuePosition={1}
          queueTotal={2}
        />
        <MergeSuggestionCard
          suggestion={withFaces({
            id: 'merge-ord-b',
            cluster_a_label: 'cluster-11',
            cluster_b_label: 'cluster-13',
            cluster_a_identity_count: 3,
            cluster_b_identity_count: 4,
            similarity: 0.87,
          })}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          onOpenOriginal={vi.fn()}
          isPending={false}
          queuePosition={2}
          queueTotal={2}
        />
      </>,
    );

    const question = 'Are these the same person?';
    const groups = screen.getAllByRole('group');
    expect(groups).toHaveLength(2);

    const groupNameA = groups[0].getAttribute('aria-labelledby')
      ? (groups[0].getAttribute('aria-labelledby') ?? '')
          .split(/\s+/)
          .filter(Boolean)
          .map((id) => document.getElementById(id)?.textContent ?? '')
          .join(' ')
      : groups[0].textContent ?? '';
    const groupNameB = groups[1].getAttribute('aria-labelledby')
      ? (groups[1].getAttribute('aria-labelledby') ?? '')
          .split(/\s+/)
          .filter(Boolean)
          .map((id) => document.getElementById(id)?.textContent ?? '')
          .join(' ')
      : groups[1].textContent ?? '';

    // Prefer Testing Library accessible-name oracles when available.
    expect(groups[0]).toHaveAccessibleName(/Merge suggestion 1 of 2/);
    expect(groups[1]).toHaveAccessibleName(/Merge suggestion 2 of 2/);
    expect(groups[0]).toHaveAccessibleName(new RegExp(question.replace('?', '\\?')));
    expect(groups[1]).toHaveAccessibleName(new RegExp(question.replace('?', '\\?')));
    expect(groupNameA).not.toBe(groupNameB);
    expect(groupNameA).toMatch(/Merge suggestion 1 of 2/);
    expect(groupNameB).toMatch(/Merge suggestion 2 of 2/);
    expect(groupNameA).toContain(question);
    expect(groupNameB).toContain(question);

    const cards = screen.getAllByTestId('acx-review-card');
    const yesA = within(cards[0]).getByRole('button', { name: 'Yes' });
    const yesB = within(cards[1]).getByRole('button', { name: 'Yes' });
    expect(yesA).toHaveAccessibleDescription(/suggestion 1 of 2|Merge suggestion 1 of 2/i);
    expect(yesB).toHaveAccessibleDescription(/suggestion 2 of 2|Merge suggestion 2 of 2/i);
    const descA = yesA.getAttribute('aria-describedby') ?? '';
    const descB = yesB.getAttribute('aria-describedby') ?? '';
    const resolveDesc = (ids: string) =>
      ids
        .split(/\s+/)
        .filter(Boolean)
        .map((id) => document.getElementById(id)?.textContent ?? '')
        .join(' ');
    expect(resolveDesc(descA)).not.toBe(resolveDesc(descB));

    const faceA = within(cards[0]).getAllByRole('button', { name: /View original photo/i });
    const faceB = within(cards[1]).getAllByRole('button', { name: /View original photo/i });
    expect(faceA).toHaveLength(2);
    expect(faceB).toHaveLength(2);
    const namesA = faceA.map((btn) => btn.getAttribute('aria-label') ?? '');
    const namesB = faceB.map((btn) => btn.getAttribute('aria-label') ?? '');
    expect(namesA.every((n) => n.includes('suggestion 1 of 2'))).toBe(true);
    expect(namesB.every((n) => n.includes('suggestion 2 of 2'))).toBe(true);
    expect(new Set([...namesA, ...namesB]).size).toBe(4);
  });

  it('BR-35: without queuePosition/queueTotal, accnames stay byte-identical to today', () => {
    render(
      <MergeSuggestionCard
        suggestion={withFaces({
          id: 'merge-fallback',
          cluster_a_label: 'cluster-7',
          cluster_b_label: 'cluster-9',
          similarity: 0.87,
        })}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onOpenOriginal={vi.fn()}
        isPending={false}
      />,
    );

    const group = screen.getByRole('group');
    expect(group).toHaveAccessibleName('Are these the same person?');
    expect(screen.queryByText(/Merge suggestion \d+ of \d+/)).toBeNull();

    const faceControls = screen.getAllByRole('button', { name: /View original photo/i });
    const controlNames = faceControls.map((btn) => btn.getAttribute('aria-label') ?? '');
    expect(controlNames).toEqual([
      'View original photo, first face',
      'View original photo, second face',
    ]);
    expect(controlNames.join(' ')).not.toMatch(/suggestion \d+ of/);

    const yes = screen.getByRole('button', { name: 'Yes' });
    expect(yes).toHaveAccessibleDescription(/first group.*second group.*87% match/i);
    expect(yes).not.toHaveAccessibleDescription(/suggestion \d+ of/i);
  });

  // BR-40: invalid ordinals (0 / NaN / Infinity / position>total) must not leak into accnames.
  // BR-45: it.each so each invalid case reports independently (for-loop masked later failures).
  it.each([
    { label: 'total=0', queuePosition: 1, queueTotal: 0 },
    { label: 'position=NaN', queuePosition: Number.NaN, queueTotal: 2 },
    { label: 'total=Infinity', queuePosition: 1, queueTotal: Number.POSITIVE_INFINITY },
    { label: 'position>total', queuePosition: 4, queueTotal: 3 },
  ])(
    'BR-40: invalid queue ordinals fall back to no-ordinal accnames (no of 0 / NaN) — $label',
    ({ label, queuePosition, queueTotal }) => {
      const fallbackFaceNames = [
        'View original photo, first face',
        'View original photo, second face',
      ];

      render(
        <MergeSuggestionCard
          suggestion={withFaces({
            id: `merge-invalid-${label}`,
            cluster_a_label: 'cluster-7',
            cluster_b_label: 'cluster-9',
            similarity: 0.87,
          })}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          onOpenOriginal={vi.fn()}
          isPending={false}
          queuePosition={queuePosition}
          queueTotal={queueTotal}
        />,
      );

      const group = screen.getByRole('group');
      expect(group, label).toHaveAccessibleName('Are these the same person?');
      expect(group, label).not.toHaveAccessibleName(/of 0|NaN|Infinity|4 of 3/i);

      const faceControls = screen.getAllByRole('button', { name: /View original photo/i });
      const controlNames = faceControls.map((btn) => btn.getAttribute('aria-label') ?? '');
      expect(controlNames, label).toEqual(fallbackFaceNames);
      expect(controlNames.join(' '), label).not.toMatch(/of 0|NaN|Infinity/i);

      const yes = screen.getByRole('button', { name: 'Yes' });
      const no = screen.getByRole('button', { name: 'No' });
      expect(yes, label).toHaveAccessibleDescription(
        /first group.*second group.*87% match/i,
      );
      expect(no, label).toHaveAccessibleDescription(
        /first group.*second group.*87% match/i,
      );
      expect(yes, label).not.toHaveAccessibleDescription(/of 0|NaN|Infinity|suggestion \d+ of/i);
      expect(no, label).not.toHaveAccessibleDescription(/of 0|NaN|Infinity|suggestion \d+ of/i);
    },
  );
});
