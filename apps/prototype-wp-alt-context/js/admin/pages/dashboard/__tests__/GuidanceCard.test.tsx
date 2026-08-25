import { render, screen } from '@testing-library/react';

import { GuidanceCard } from '../GuidanceCard';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
  },
}));

describe('GuidanceCard', () => {
  it('renders pending-review guidance first when pending clusters exist', () => {
    render(
      <GuidanceCard
        stats={{
          people_count: 0,
          assigned_clusters_count: 0,
          pending_clusters_count: 5,
          media_with_faces_count: 10,
          unassigned_persons_count: 2,
        }}
      />,
    );

    expect(screen.getByText('5 faces are waiting for names.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Review Queue' })).toHaveAttribute('href', '#/workbench?advanced=open');
  });

  it('renders first-use guidance when there are no people', () => {
    render(
      <GuidanceCard
        stats={{
          people_count: 0,
          assigned_clusters_count: 0,
          pending_clusters_count: 0,
          media_with_faces_count: 0,
          unassigned_persons_count: 0,
        }}
      />,
    );

    expect(screen.getByText('Start by scanning your media library for faces.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Scan tab' })).toHaveAttribute('href', '#/workbench?tab=scan');
  });

  it('prioritizes unassigned-person guidance ahead of first-use fallback', () => {
    render(
      <GuidanceCard
        stats={{
          people_count: 0,
          assigned_clusters_count: 0,
          pending_clusters_count: 0,
          media_with_faces_count: 8,
          unassigned_persons_count: 2,
        }}
      />,
    );

    expect(screen.getByText('2 persons have no assigned face groups.')).toBeInTheDocument();
    expect(screen.queryByText('Start by scanning your media library for faces.')).not.toBeInTheDocument();
  });

  it('renders unassigned-person guidance when unassigned persons exist', () => {
    render(
      <GuidanceCard
        stats={{
          people_count: 4,
          assigned_clusters_count: 2,
          pending_clusters_count: 0,
          media_with_faces_count: 8,
          unassigned_persons_count: 2,
        }}
      />,
    );

    expect(screen.getByText('2 persons have no assigned face groups.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Review 2 unassigned persons' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan',
    );
    expect(screen.getByText('2', { selector: '.acx-dashboard__guidance-count' })).toBeInTheDocument();
  });

  it('uses singular copy for one unassigned person', () => {
    render(
      <GuidanceCard
        stats={{
          people_count: 1,
          assigned_clusters_count: 0,
          pending_clusters_count: 0,
          media_with_faces_count: 1,
          unassigned_persons_count: 1,
        }}
      />,
    );

    expect(screen.getByText('1 person has no assigned face groups.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Review 1 unassigned person' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan',
    );
  });

  it('renders all-caught-up guidance by default', () => {
    render(
      <GuidanceCard
        stats={{
          people_count: 3,
          assigned_clusters_count: 3,
          pending_clusters_count: 0,
          media_with_faces_count: 8,
          unassigned_persons_count: 0,
        }}
      />,
    );

    expect(screen.getByText('All caught up. New faces will appear here for review.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Review Queue' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan',
    );
  });
});
