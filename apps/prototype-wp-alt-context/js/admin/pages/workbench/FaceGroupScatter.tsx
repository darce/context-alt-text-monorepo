import React from 'react';
import { __ } from '@wordpress/i18n';

import { EmptyState, EmptyStateVariant } from '../../components/ui/EmptyState';
import { toWorkbench } from '../../navigation/appLinks';

/** z-cluster-umap declared states (D-23). */
export const FACE_GROUP_SCATTER_STATE = {
  default: 'default',
  loading: 'loading',
  empty: 'empty',
  error: 'error',
  first_time: 'first_time',
  degraded: 'degraded',
} as const;

export type FaceGroupScatterState =
  (typeof FACE_GROUP_SCATTER_STATE)[keyof typeof FACE_GROUP_SCATTER_STATE];

export const FACE_GROUP_SCATTER_COPY = {
  loading: __('Loading face group scatter…', 'alt-context'),
  empty: __('No face groups to plot yet.', 'alt-context'),
  error: __('Unable to load face group scatter.', 'alt-context'),
  firstTime: __('Scan media to plot face groups.', 'alt-context'),
  degraded: __('Face group scatter is running with reduced data.', 'alt-context'),
  retry: __('Retry', 'alt-context'),
  scan: __('Go to Scan', 'alt-context'),
} as const;

export interface FaceGroupScatterProps {
  state: FaceGroupScatterState;
  onRetry?: () => void;
}

export const FaceGroupScatter = ({ state, onRetry }: FaceGroupScatterProps): React.JSX.Element => (
  <section
    className="acx-face-group-scatter"
    aria-label={__('Face group scatter', 'alt-context')}
    data-testid="acx-zone-z-cluster-umap"
    data-acx-zone-state={state}
  >
    {state === FACE_GROUP_SCATTER_STATE.loading ? <p>{FACE_GROUP_SCATTER_COPY.loading}</p> : null}
    {state === FACE_GROUP_SCATTER_STATE.empty ? (
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading={FACE_GROUP_SCATTER_COPY.empty}
        body={FACE_GROUP_SCATTER_COPY.firstTime}
        action={{ label: FACE_GROUP_SCATTER_COPY.scan, href: toWorkbench({ tab: 'scan' }) }}
        headingLevel={3}
      />
    ) : null}
    {state === FACE_GROUP_SCATTER_STATE.first_time ? (
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading={FACE_GROUP_SCATTER_COPY.firstTime}
        body={FACE_GROUP_SCATTER_COPY.empty}
        action={{ label: FACE_GROUP_SCATTER_COPY.scan, href: toWorkbench({ tab: 'scan' }) }}
        headingLevel={3}
      />
    ) : null}
    {state === FACE_GROUP_SCATTER_STATE.error ? (
      <div className="acx-error-state" role="alert">
        <p>{FACE_GROUP_SCATTER_COPY.error}</p>
        {onRetry ? (
          <button type="button" className="acx-button acx-button--secondary" onClick={onRetry}>
            {FACE_GROUP_SCATTER_COPY.retry}
          </button>
        ) : null}
      </div>
    ) : null}
    {state === FACE_GROUP_SCATTER_STATE.degraded ? (
      <p role="status">{FACE_GROUP_SCATTER_COPY.degraded}</p>
    ) : null}
  </section>
);
