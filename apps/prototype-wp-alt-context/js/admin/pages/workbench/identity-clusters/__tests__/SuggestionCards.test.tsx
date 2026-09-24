import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ReviewSuggestion } from '../suggestionReviewItems';
import { SuggestionCard } from '../SuggestionCards';
import preview from './fixtures/gpuflow-candidate-preview.json';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

// Radix Avatar's Image gates on Image.onload, which never fires in JSDOM.
vi.mock('@radix-ui/react-avatar', async () => {
  const ReactMod = await import('react');
  return {
    Root: ReactMod.forwardRef(function MockRoot({ children, ...props }: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement(
        'span',
        { ...props, ref } as React.HTMLAttributes<HTMLSpanElement>,
        children as React.ReactNode,
      );
    }),
    Image: ReactMod.forwardRef(function MockImage(props: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement('img', { ...props, ref } as React.ImgHTMLAttributes<HTMLImageElement>);
    }),
    Fallback: ReactMod.forwardRef(function MockFallback() {
      return null;
    }),
  };
});

const baseSuggestion: ReviewSuggestion = {
  suggestionId: 'sugg-1',
  identityId: 'identity-1',
  clusterId: 'cluster-1',
  label: 'Alex',
  similarity: 0.9,
  identityCount: 3,
};

const imageSrcCount = (src: string): number =>
  screen.queryAllByRole('img').filter((element) => element.getAttribute('src') === src).length;

describe('SuggestionCard GPUFLOW-1 candidate preview', () => {
  it('renders distinct candidate and representative avatars', () => {
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          enrichment: { ...preview.candidate, ...preview.representative },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    expect(screen.getByAltText('Candidate face, position 1 of 1')).toHaveAttribute(
      'src',
      preview.candidate.identityMediaUrl,
    );
    expect(screen.getByAltText('Alex stored face, position 1 of 3')).toHaveAttribute(
      'src',
      preview.representative.representativeMediaUrl,
    );
    expect(preview.candidate.identityMediaUrl).not.toBe(preview.representative.representativeMediaUrl);
    expect(imageSrcCount(preview.candidate.identityMediaUrl)).toBe(1);
    expect(imageSrcCount(preview.representative.representativeMediaUrl)).toBe(1);
  });

  it('shows an explicit placeholder when no noncandidate representative exists', () => {
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          enrichment: { ...preview.candidate, ...preview.nullRepresentative },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    expect(screen.getByAltText('Candidate face, position 1 of 1')).toHaveAttribute(
      'src',
      preview.candidate.identityMediaUrl,
    );
    expect(screen.getByRole('img', { name: 'Representative image unavailable' })).toBeInTheDocument();
    expect(screen.queryByAltText('Alex stored face, position 1 of 3')).toBeNull();
    expect(imageSrcCount(preview.candidate.identityMediaUrl)).toBe(1);
  });

  it.each([
    ...preview.nonCroppableBboxes,
    { x: Number.NaN, y: 20, width: 30, height: 40 },
    { x: 10, y: 20, width: 30, height: Number.POSITIVE_INFINITY },
  ])('does not mount crop controls for invalid geometry %j', (bbox) => {
    const { container } = render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          enrichment: {
            ...preview.candidate,
            ...preview.representative,
            identityBbox: bbox,
            representativeBbox: bbox,
          },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onOpenOriginal={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    expect(screen.queryByRole('button', { name: 'View original photo' })).toBeNull();
    expect(container.querySelector('.acx-face-thumbnail')).toBeNull();
    expect(screen.queryByAltText('Candidate face, position 1 of 1')).toBeNull();
    expect(screen.queryByAltText('Alex stored face, position 1 of 3')).toBeNull();
    expect(screen.getAllByRole('img', { name: 'Representative image unavailable' })).toHaveLength(2);
    expect(imageSrcCount(preview.candidate.identityMediaUrl)).toBe(0);
    expect(imageSrcCount(preview.representative.representativeMediaUrl)).toBe(0);
  });

  it.each(preview.nonCroppableBboxes)(
    'falls back to a placeholder when the representative bbox is not croppable %j',
    (bbox) => {
      const { container } = render(
        <SuggestionCard
          suggestion={{
            ...baseSuggestion,
            enrichment: {
              ...preview.candidate,
              ...preview.representative,
              representativeBbox: bbox,
            },
          }}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          onOpenOriginal={vi.fn()}
          isPending={false}
          lowConfidenceThreshold={0.5}
        />,
      );

      expect(screen.getByAltText('Candidate face, position 1 of 1')).toHaveAttribute(
        'src',
        preview.candidate.identityMediaUrl,
      );
      expect(container.querySelectorAll('.acx-face-thumbnail')).toHaveLength(1);
      expect(screen.getByRole('img', { name: 'Representative image unavailable' })).toBeInTheDocument();
      expect(screen.queryByAltText('Alex stored face, position 1 of 3')).toBeNull();
      expect(imageSrcCount(preview.candidate.identityMediaUrl)).toBe(1);
      expect(imageSrcCount(preview.representative.representativeMediaUrl)).toBe(0);
    },
  );
});

describe('SuggestionCard BR-41 group accname', () => {
  it.each([
    { label: '1 of 2', queuePosition: 1, queueTotal: 2 },
    { label: '3 of 3', queuePosition: 3, queueTotal: 3 },
    { label: '1 of 1', queuePosition: 1, queueTotal: 1 },
  ])(
    'card root has Face suggestion $label when ordinal pair valid',
    ({ queuePosition, queueTotal }) => {
      render(
        <SuggestionCard
          suggestion={{ ...baseSuggestion, suggestionId: `sugg-${queuePosition}-${queueTotal}` }}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          isPending={false}
          lowConfidenceThreshold={0.5}
          queuePosition={queuePosition}
          queueTotal={queueTotal}
        />,
      );

      const card = screen.getByTestId('acx-review-card');
      expect(card).toHaveAttribute('role', 'group');
      expect(card).toHaveAccessibleName(
        new RegExp(`Face suggestion ${queuePosition} of ${queueTotal}`),
      );
    },
  );

  it.each([
    { label: 'total=0', queuePosition: 1, queueTotal: 0 },
    { label: 'position=NaN', queuePosition: Number.NaN, queueTotal: 2 },
    { label: 'total=Infinity', queuePosition: 1, queueTotal: Number.POSITIVE_INFINITY },
    { label: 'position=float', queuePosition: 1.5, queueTotal: 2 },
    { label: 'position>total', queuePosition: 4, queueTotal: 3 },
  ])(
    'BR-41: invalid queue ordinals fall back to kind-only Face suggestion — $label',
    ({ label, queuePosition, queueTotal }) => {
      render(
        <SuggestionCard
          suggestion={{ ...baseSuggestion, suggestionId: `sugg-${label}` }}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          isPending={false}
          lowConfidenceThreshold={0.5}
          queuePosition={queuePosition}
          queueTotal={queueTotal}
        />,
      );

      const card = screen.getByTestId('acx-review-card');
      expect(card, label).toHaveAccessibleName('Face suggestion');
      expect(card, label).not.toHaveAccessibleName(/of 0|NaN|Infinity|1\.5|4 of 3/i);
    },
  );

  it('BR-41: without queuePosition/queueTotal, accname is kind-only Face suggestion (never empty)', () => {
    render(
      <SuggestionCard
        suggestion={baseSuggestion}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    const card = screen.getByTestId('acx-review-card');
    expect(card).toHaveAccessibleName('Face suggestion');
    expect(screen.queryByText(/Face suggestion \d+ of \d+/)).toBeNull();
  });

  it('Yes fires onAccept once and does not preview a close-match group on the card', async () => {
    const onAccept = vi.fn();
    const user = userEvent.setup();
    render(
      <SuggestionCard
        suggestion={baseSuggestion}
        onAccept={onAccept}
        onReject={vi.fn()}
        onReview={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Show stored faces' }));
    await user.click(screen.getByRole('button', { name: 'Yes' }));
    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByText(/close matches/i)).not.toBeInTheDocument();
  });

  it('renders the face-count string and separate stored-face and cluster actions (UXW2-3-R1-11)', () => {
    render(
      <SuggestionCard
        suggestion={baseSuggestion}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onReview={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    expect(screen.getByText(/3 faces/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show stored faces' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open cluster' })).toBeInTheDocument();
  });

  it('opens the cluster separately from showing stored faces', async () => {
    const onReview = vi.fn();
    const user = userEvent.setup();
    render(
      <SuggestionCard
        suggestion={baseSuggestion}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onReview={onReview}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Open cluster' }));

    expect(onReview).toHaveBeenCalledTimes(1);
    expect(onReview).toHaveBeenCalledWith('cluster-1');
    expect(screen.queryByRole('list', { name: 'Stored faces for Alex' })).toBeNull();
  });
});

describe('SuggestionCard lightbox target (UXW2-6)', () => {
  it('passes identity media id and face id when opening the candidate original', async () => {
    const onOpenOriginal = vi.fn();
    const user = userEvent.setup();
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          identityId: 'identity-1',
          enrichment: {
            identityMediaId: 42,
            identityMediaUrl: 'https://example.com/candidate.jpg',
            identityBbox: { x: 5, y: 6, width: 40, height: 50 },
          },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onOpenOriginal={onOpenOriginal}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'View original photo' }));
    expect(onOpenOriginal).toHaveBeenCalledWith({
      mediaUrl: 'https://example.com/candidate.jpg',
      bbox: { x: 5, y: 6, width: 40, height: 50 },
      label: 'Candidate face, position 1 of 1',
      mediaId: 42,
      identityId: 'identity-1',
    });
  });

  it('omits mediaId when the candidate media id is missing so the lightbox does not fetch', async () => {
    const onOpenOriginal = vi.fn();
    const user = userEvent.setup();
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          identityId: 'identity-1',
          enrichment: {
            identityMediaUrl: 'https://example.com/candidate.jpg',
            identityBbox: { x: 5, y: 6, width: 40, height: 50 },
          },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onOpenOriginal={onOpenOriginal}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'View original photo' }));
    expect(onOpenOriginal).toHaveBeenCalledWith({
      mediaUrl: 'https://example.com/candidate.jpg',
      bbox: { x: 5, y: 6, width: 40, height: 50 },
      label: 'Candidate face, position 1 of 1',
      identityId: 'identity-1',
    });
    expect(onOpenOriginal.mock.calls[0][0]).not.toHaveProperty('mediaId');
  });

  it('passes representative media id when opening the stored-face original', async () => {
    const onOpenOriginal = vi.fn();
    const user = userEvent.setup();
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          enrichment: {
            ...preview.representative,
          },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onOpenOriginal={onOpenOriginal}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'View original photo' }));
    expect(onOpenOriginal).toHaveBeenCalledWith({
      mediaUrl: preview.representative.representativeMediaUrl,
      bbox: preview.representative.representativeBbox,
      label: 'Alex stored face, position 1 of 3',
      mediaId: preview.representative.representativeMediaId,
    });
  });

  it('does not reuse the candidate media id for the representative crop', async () => {
    const onOpenOriginal = vi.fn();
    const user = userEvent.setup();
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          enrichment: {
            ...preview.candidate,
            ...preview.representative,
          },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onOpenOriginal={onOpenOriginal}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    expect(imageSrcCount(preview.candidate.identityMediaUrl)).toBe(1);
    expect(imageSrcCount(preview.representative.representativeMediaUrl)).toBe(1);

    const cropControls = screen.getAllByRole('button', { name: 'View original photo' });
    expect(cropControls).toHaveLength(2);
    await user.click(cropControls[1]);
    expect(onOpenOriginal).toHaveBeenCalledWith({
      mediaUrl: preview.representative.representativeMediaUrl,
      bbox: preview.representative.representativeBbox,
      label: 'Alex stored face, position 1 of 3',
      mediaId: preview.representative.representativeMediaId,
    });
    expect(onOpenOriginal.mock.calls[0][0].mediaId).not.toBe(preview.candidate.identityMediaId);
  });

  it('omits mediaId when the representative media id is missing so the lightbox does not fetch', async () => {
    const onOpenOriginal = vi.fn();
    const user = userEvent.setup();
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          enrichment: {
            representativeMediaUrl: preview.representative.representativeMediaUrl,
            representativeBbox: preview.representative.representativeBbox,
          },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onOpenOriginal={onOpenOriginal}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'View original photo' }));
    expect(onOpenOriginal).toHaveBeenCalledWith({
      mediaUrl: preview.representative.representativeMediaUrl,
      bbox: preview.representative.representativeBbox,
      label: 'Alex stored face, position 1 of 3',
    });
    expect(onOpenOriginal.mock.calls[0][0]).not.toHaveProperty('mediaId');
  });
});

describe('SuggestionCard UXC-02 stored-reference disclosure', () => {
  it('DUX-L8-RV-01: keeps approval blocked until the stored-face disclosure is rendered', async () => {
    const onAccept = vi.fn();
    const onReview = vi.fn();
    const user = userEvent.setup();

    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          identityCount: 3,
          enrichment: {
            representativeThumbUrl: 'https://example.com/alex-stored.jpg',
          },
        }}
        onAccept={onAccept}
        onReject={vi.fn()}
        onReview={onReview}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    expect(screen.getByText('2 more faces not shown')).toBeInTheDocument();
    const approve = screen.getByRole('button', { name: 'Yes' });
    expect(approve).toBeDisabled();
    expect(screen.queryByRole('list', { name: 'Stored faces for Alex' })).toBeNull();

    const showStoredFaces = screen.getByRole('button', { name: 'Show stored faces' });
    expect(showStoredFaces).toHaveAttribute('aria-expanded', 'false');
    expect(showStoredFaces).toHaveAttribute('aria-controls', 'acx-stored-face-list-sugg-1');
    await user.click(showStoredFaces);

    expect(onReview).not.toHaveBeenCalled();
    expect(screen.getByRole('list', { name: 'Stored faces for Alex' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hide stored faces' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByRole('list', { name: 'Stored faces for Alex' })).toHaveTextContent(
      'Stored face 2 of 3 — Image unavailable',
    );
    expect(screen.getByRole('list', { name: 'Stored faces for Alex' })).toHaveTextContent(
      'Stored face 3 of 3 — Image unavailable',
    );
    expect(approve).toBeEnabled();
    await user.click(approve);
    expect(onAccept).toHaveBeenCalledTimes(1);
  });

  it('DUX-L8-RV-01/02: fails closed without onReview and discloses text for unavailable images', async () => {
    const user = userEvent.setup();
    render(
      <SuggestionCard
        suggestion={{ ...baseSuggestion, identityCount: 3 }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    const approve = screen.getByRole('button', { name: 'Yes' });
    expect(approve).toBeDisabled();
    expect(screen.getByText('2 more faces not shown')).toBeInTheDocument();
    expect(screen.getByText('Show stored faces first to approve.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Show stored faces' }));

    const faceList = screen.getByRole('list', { name: 'Stored faces for Alex' });
    expect(faceList).toHaveTextContent('Stored face 1 of 3 — Image unavailable');
    expect(faceList).toHaveTextContent('Stored face 2 of 3 — Image unavailable');
    expect(faceList).toHaveTextContent('Stored face 3 of 3 — Image unavailable');
    expect(approve).toBeEnabled();
  });

  it('DUX-L8-RV-03/04: exposes a visible associated block reason and keeps static count out of live regions', () => {
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          identityCount: 3,
          enrichment: { representativeThumbUrl: 'https://example.com/alex-stored.jpg' },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    const approve = screen.getByRole('button', { name: 'Yes' });
    const reason = screen.getByText('Show stored faces first to approve.');
    expect(reason).toBeVisible();
    expect(approve).toHaveAttribute('aria-disabled', 'true');
    expect(approve).toHaveAttribute('aria-describedby', reason.id);
    expect(screen.getByText('2 more faces not shown')).not.toHaveAttribute('role', 'status');
  });

  it('gives candidate and stored-reference images source-and-position alt text', () => {
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          label: 'Alex',
          identityCount: 3,
          enrichment: {
            identityMediaUrl: 'https://example.com/candidate.jpg',
            identityBbox: { x: 5, y: 6, width: 40, height: 50 },
            representativeMediaUrl: 'https://example.com/alex-stored.jpg',
            representativeBbox: { x: 10, y: 12, width: 30, height: 35 },
          },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onReview={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    expect(screen.getByAltText('Candidate face, position 1 of 1')).toHaveAttribute(
      'src',
      'https://example.com/candidate.jpg',
    );
    expect(screen.getByAltText('Alex stored face, position 1 of 3')).toHaveAttribute(
      'src',
      'https://example.com/alex-stored.jpg',
    );
  });
});

describe('SuggestionCard L4R-01 Avatar alt + L4R-02 assertTruthyLabel', () => {
  it('L4R-01: Avatar representative branch img alt equals person displayLabel', () => {
    // Predicted first failure: alt is generic "Cluster representative" (pre-displayLabel change).
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          label: 'Jordan Lee',
          enrichment: {
            representativeThumbUrl: 'https://example.com/rep-thumb.jpg',
          },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    const repImg = screen.getByAltText('Jordan Lee stored face, position 1 of 3');
    expect(repImg).toHaveAttribute('src', 'https://example.com/rep-thumb.jpg');
    expect(screen.queryByAltText('Cluster representative')).toBeNull();
  });

  it('L4R-02: assertTruthyLabel throws for whitespace-only label', () => {
    // Predicted first failure: whitespace-only label accepted (length>0 without trim).
    expect(() =>
      render(
        <SuggestionCard
          suggestion={{ ...baseSuggestion, label: ' ' }}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          isPending={false}
          lowConfidenceThreshold={0.5}
        />,
      ),
    ).toThrow('SuggestionCard requires a truthy suggestion.label');
  });
});
