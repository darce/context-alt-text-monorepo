import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  faceOverlayDomId,
  type FaceOverlayIdentity,
} from '../../components/ui/FaceOverlayLayer';
import { ATTACHMENT_EDIT_COPY } from '../copy';
import {
  UncuratedFaceList,
  selectUncuratedFacesInReadingOrder,
  uncuratedListRowDomId,
} from '../UncuratedFaceList';

const WORKBENCH_URL =
  'https://example.test/wp-admin/admin.php?page=alt-context-workbench';
const MEDIA_URL = 'https://example.test/photo.jpg';

/** API order intentionally ≠ visual (bbox.y, bbox.x) reading order. */
const outOfOrderFixture = (): FaceOverlayIdentity[] => {
  return [
    // Uncurated — sorts second among uncurated (y=200, x=300)
    {
      identity_id: 'u-late',
      bbox: { x: 300, y: 200, width: 40, height: 40 },
      cluster_label: null,
      is_auto_label: true,
    },
    // Curated — excluded from list
    {
      identity_id: 'c-early',
      bbox: { x: 20, y: 10, width: 50, height: 50 },
      cluster_label: 'Alex',
      is_auto_label: false,
    },
    // Uncurated — sorts first among uncurated (y=200, x=50)
    {
      identity_id: 'u-early',
      bbox: { x: 50, y: 200, width: 40, height: 40 },
      cluster_label: 'cluster-abc',
      is_auto_label: true,
    },
    // Auto-label with name still uncurated [AIPX-07]
    {
      identity_id: 'u-auto',
      bbox: { x: 10, y: 400, width: 40, height: 40 },
      cluster_label: 'cluster-xyz',
      is_auto_label: true,
    },
  ];
};

describe('selectUncuratedFacesInReadingOrder', () => {
  it('drops curated faces and sorts by bbox.y then bbox.x', () => {
    const ordered = selectUncuratedFacesInReadingOrder(outOfOrderFixture());
    expect(ordered.map((f) => f.identity_id)).toEqual(['u-early', 'u-late', 'u-auto']);
  });
});

describe('UncuratedFaceList', () => {
  it('renders one row per uncurated face with FaceThumbnail crop', () => {
    render(
      <UncuratedFaceList
        identities={outOfOrderFixture()}
        mediaUrl={MEDIA_URL}
        workbenchUrl={WORKBENCH_URL}
      />,
    );

    const list = screen.getByTestId('acx-uncurated-face-list');
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => r.getAttribute('data-face-id'))).toEqual([
      'u-early',
      'u-late',
      'u-auto',
    ]);

    expect(screen.getByText('Unnamed face 1 of 3')).toBeInTheDocument();
    expect(screen.getByText('Unnamed face 2 of 3')).toBeInTheDocument();
    expect(screen.getByText('Unnamed face 3 of 3')).toBeInTheDocument();

    // FaceThumbnail sm crops are present (img alt = row label).
    expect(screen.getByAltText('Unnamed face 1 of 3')).toBeInTheDocument();
  });

  it('links "Name this person" to the plain workbench admin URL only (no invented params)', () => {
    render(
      <UncuratedFaceList
        identities={outOfOrderFixture()}
        mediaUrl={MEDIA_URL}
        workbenchUrl={WORKBENCH_URL}
      />,
    );

    const links = screen.getAllByRole('link', { name: ATTACHMENT_EDIT_COPY.nameThisPerson });
    expect(links).toHaveLength(3);
    for (const link of links) {
      expect(link).toHaveAttribute('href', WORKBENCH_URL);
      // Closed deep-link decision: no media-filter query param until E21-10.
      expect(link.getAttribute('href')).not.toMatch(/media_id|attachment|filter=/i);
    }
  });

  it('pairs list rows to overlay markers via aria-controls / aria-describedby', () => {
    render(
      <UncuratedFaceList
        identities={outOfOrderFixture()}
        mediaUrl={MEDIA_URL}
        workbenchUrl={WORKBENCH_URL}
      />,
    );

    const link = screen.getByTestId('acx-name-person-link-u-early');
    expect(link).toHaveAttribute('aria-controls', faceOverlayDomId('u-early'));
    expect(link).toHaveAttribute('aria-describedby', faceOverlayDomId('u-early'));
    expect(document.getElementById(uncuratedListRowDomId('u-early'))).toBeTruthy();
  });

  it('sanitizes hostile identity_id into selector-safe list/overlay aria ids [UXP5-BRV-02]', () => {
    const hostile = 'evil "id" {x}';
    render(
      <UncuratedFaceList
        identities={[
          {
            identity_id: hostile,
            bbox: { x: 10, y: 10, width: 40, height: 40 },
          },
        ]}
        mediaUrl={MEDIA_URL}
        workbenchUrl={WORKBENCH_URL}
        highlightedFaceId={hostile}
      />,
    );

    const overlayId = faceOverlayDomId(hostile);
    const rowId = uncuratedListRowDomId(hostile);
    expect(overlayId).toMatch(/^acx-face-overlay-[A-Za-z0-9_-]+$/);
    expect(rowId).toMatch(/^acx-uncurated-list-[A-Za-z0-9_-]+$/);
    expect(document.getElementById(rowId)).toHaveClass(
      'acx-uncurated-face-list__row--highlighted',
    );
    // data-testid still uses raw id; aria relationships use sanitized tokens.
    const link = screen.getByTestId(`acx-name-person-link-${hostile}`);
    expect(link).toHaveAttribute('aria-controls', overlayId);
    expect(link).toHaveAttribute('aria-describedby', overlayId);
    expect(document.querySelector(`#${CSS.escape(rowId)}`)).not.toBeNull();
  });

  it('highlights a row when highlightedFaceId is set from outside (controlled API)', () => {
    render(
      <UncuratedFaceList
        identities={outOfOrderFixture()}
        mediaUrl={MEDIA_URL}
        workbenchUrl={WORKBENCH_URL}
        highlightedFaceId="u-late"
      />,
    );

    const row = document.getElementById(uncuratedListRowDomId('u-late'));
    expect(row).toHaveClass('acx-uncurated-face-list__row--highlighted');
    expect(row?.dataset.highlighted).toBe('true');

    const other = document.getElementById(uncuratedListRowDomId('u-early'));
    expect(other).not.toHaveClass('acx-uncurated-face-list__row--highlighted');
  });

  it('fires onHighlightChange on row hover and link focus', () => {
    const onHighlightChange = vi.fn();
    render(
      <UncuratedFaceList
        identities={outOfOrderFixture()}
        mediaUrl={MEDIA_URL}
        workbenchUrl={WORKBENCH_URL}
        onHighlightChange={onHighlightChange}
      />,
    );

    const row = document.getElementById(uncuratedListRowDomId('u-early'));
    expect(row).toBeTruthy();
    fireEvent.mouseEnter(row!);
    expect(onHighlightChange).toHaveBeenCalledWith('u-early');

    fireEvent.mouseLeave(row!);
    expect(onHighlightChange).toHaveBeenCalledWith(null);

    onHighlightChange.mockClear();
    const link = screen.getByTestId('acx-name-person-link-u-late');
    // Focus only — avoid jsdom navigation on <a> click.
    link.focus();
    fireEvent.focusIn(link);
    expect(onHighlightChange).toHaveBeenCalledWith('u-late');
  });

  it('returns null when every face is curated', () => {
    const { container } = render(
      <UncuratedFaceList
        identities={[
          {
            identity_id: 'c1',
            bbox: { x: 0, y: 0, width: 40, height: 40 },
            cluster_label: 'Sam',
            is_auto_label: false,
          },
        ]}
        mediaUrl={MEDIA_URL}
        workbenchUrl={WORKBENCH_URL}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
