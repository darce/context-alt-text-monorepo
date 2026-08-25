import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  FACE_GROUP_SCATTER_COPY,
  FACE_GROUP_SCATTER_STATE,
  FaceGroupScatter,
} from '../FaceGroupScatter';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

describe('D-23 FaceGroupScatter (z-cluster-umap)', () => {
  it('renders loading', () => {
    render(<FaceGroupScatter state={FACE_GROUP_SCATTER_STATE.loading} />);
    expect(screen.getByText('Loading face group scatter…')).toBeInTheDocument();
  });

  it('renders empty with a front door', () => {
    render(<FaceGroupScatter state={FACE_GROUP_SCATTER_STATE.empty} />);
    expect(screen.getByText(FACE_GROUP_SCATTER_COPY.empty)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: FACE_GROUP_SCATTER_COPY.scan })).toBeInTheDocument();
  });

  it('renders error', () => {
    render(<FaceGroupScatter state={FACE_GROUP_SCATTER_STATE.error} onRetry={() => undefined} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load face group scatter.');
  });

  it('renders first_time', () => {
    render(<FaceGroupScatter state={FACE_GROUP_SCATTER_STATE.first_time} />);
    expect(screen.getByText(FACE_GROUP_SCATTER_COPY.firstTime)).toBeInTheDocument();
  });

  it('renders degraded', () => {
    render(<FaceGroupScatter state={FACE_GROUP_SCATTER_STATE.degraded} />);
    expect(screen.getByText(FACE_GROUP_SCATTER_COPY.degraded)).toBeInTheDocument();
  });
});
