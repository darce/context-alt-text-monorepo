import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { FACE_GROUP_SCATTER_STATE, FaceGroupScatter } from '../FaceGroupScatter';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

describe('D-23 FaceGroupScatter (z-cluster-umap)', () => {
  it('renders loading', () => {
    render(<FaceGroupScatter state={FACE_GROUP_SCATTER_STATE.loading} />);
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Loading face-group status…');
    expect(status).toHaveAttribute('aria-live', 'polite');
  });

  it('renders empty with a front door', () => {
    render(<FaceGroupScatter state={FACE_GROUP_SCATTER_STATE.empty} />);
    expect(screen.getByText('No face groups yet.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Scan' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan',
    );
  });

  it('renders error', () => {
    render(<FaceGroupScatter state={FACE_GROUP_SCATTER_STATE.error} onRetry={() => undefined} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load face-group status.');
  });

  it('renders first_time', () => {
    render(<FaceGroupScatter state={FACE_GROUP_SCATTER_STATE.first_time} />);
    expect(screen.getByText('Scan media to find face groups.')).toBeInTheDocument();
  });

  it('renders degraded', () => {
    render(<FaceGroupScatter state={FACE_GROUP_SCATTER_STATE.degraded} />);
    expect(screen.getByText('Face-group status is running with reduced data.')).toBeInTheDocument();
  });
});
