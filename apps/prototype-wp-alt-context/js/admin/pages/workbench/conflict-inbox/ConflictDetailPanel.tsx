import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { ConflictResolutionChoice } from '../../../api/recognition';
import { useConflictDetail } from '../../../hooks/useConflictDetail';
import {
  formatEntityLabel,
  formatTimestamp,
  getConflictTypeLabel,
  getAcceptBackendPreview,
  getDifferenceEntries,
  getResolutionButtonLabel,
  getResolutionConfirmation,
  getUnsupportedExplanation,
} from './conflictInboxUtils';

const DETAIL_STATUS = {
  alertRole: 'alert',
  live: 'polite',
  role: 'status',
  testId: 'acx-conflict-detail-status',
} as const;

interface ConflictDetailPanelProps {
  conflictId: number | null;
  pendingChoice: ConflictResolutionChoice | null;
  onRequestResolve: (choice: ConflictResolutionChoice) => void;
  isResolving: boolean;
  disabledReasonId?: string;
}

export const ConflictDetailPanel = ({
  conflictId,
  pendingChoice,
  onRequestResolve,
  isResolving,
  disabledReasonId,
}: ConflictDetailPanelProps): React.JSX.Element => {
  const detailQuery = useConflictDetail(conflictId);
  const detailStatus =
    conflictId !== null && detailQuery.isLoading ? __('Loading conflict detail…', 'alt-context') : '';
  const statusRegion = (
    <div
      className="screen-reader-text"
      role={DETAIL_STATUS.role}
      aria-live={DETAIL_STATUS.live}
      data-testid={DETAIL_STATUS.testId}
    >
      {detailStatus}
    </div>
  );

  if (conflictId === null) {
    return <div>{statusRegion}</div>;
  }

  if (detailQuery.isLoading) {
    return (
      <div aria-busy="true">
        {statusRegion}
        <p>{__('Loading conflict detail…', 'alt-context')}</p>
      </div>
    );
  }

  if (detailQuery.isError || !detailQuery.data) {
    return (
      <div>
        {statusRegion}
        <div className="acx-error-state" role={DETAIL_STATUS.alertRole}>
          <span aria-hidden="true">⚠</span>
          <p>{__('Unable to load conflict detail.', 'alt-context')}</p>
        </div>
      </div>
    );
  }

  const { conflict } = detailQuery.data;
  const unsupportedExplanation = getUnsupportedExplanation(conflict);
  const differences = getDifferenceEntries(conflict);
  const acceptPreview = getAcceptBackendPreview(conflict);

  return (
    <div className="acx-workbench__panel">
      {statusRegion}
      <h3>{__('Conflict Detail', 'alt-context')}</h3>
      <p>{getConflictTypeLabel(conflict)}</p>
      <p>
        {sprintf(
          __('Entity: %1$s · Type: %2$s · Logged: %3$s', 'alt-context'),
          formatEntityLabel(conflict),
          conflict.entity_type,
          formatTimestamp(conflict.created_at),
        )}
      </p>
      {unsupportedExplanation ? <p>{unsupportedExplanation}</p> : null}
      {differences.length > 0 ? (
        <div>
          <h4>{__('Differing fields', 'alt-context')}</h4>
          <ul className="acx-dashboard__activity-list">
            {differences.map((difference) => (
              <li key={difference.key} className="acx-dashboard__activity-item">
                <div>
                  <strong>{difference.key}</strong>
                  <p>{sprintf(__('Machine: %s', 'alt-context'), difference.machineValue)}</p>
                  <p>{sprintf(__('Local: %s', 'alt-context'), difference.localValue)}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {acceptPreview ? (
        <div>
          <h4>{__('Accept backend preview', 'alt-context')}</h4>
          <p>{acceptPreview.summary}</p>
          {acceptPreview.payload ? <pre>{JSON.stringify(acceptPreview.payload, null, 2)}</pre> : null}
        </div>
      ) : null}
      <div className="acx-workbench__layout">
        <section aria-label={__('Machine payload', 'alt-context')}>
          <h4>{__('Machine payload', 'alt-context')}</h4>
          <pre>{JSON.stringify(conflict.machine_payload, null, 2)}</pre>
        </section>
        <section aria-label={__('Local payload', 'alt-context')}>
          <h4>{__('Local payload', 'alt-context')}</h4>
          <pre>{JSON.stringify(conflict.local_payload, null, 2)}</pre>
        </section>
      </div>
      {conflict.allowed_resolutions.length > 0 ? (
        <div className="acx-dashboard__actions">
          {conflict.allowed_resolutions.map((choice) => (
            <button
              key={choice}
              type="button"
              className="button button-secondary"
              onClick={() => {
                void onRequestResolve(choice);
              }}
              disabled={isResolving}
              aria-disabled={isResolving ? true : undefined}
              aria-describedby={isResolving ? disabledReasonId : undefined}
            >
              {pendingChoice === choice ? __('Confirm', 'alt-context') : getResolutionButtonLabel(choice)}
            </button>
          ))}
        </div>
      ) : (
        <p>{__('No resolution actions are available for this conflict.', 'alt-context')}</p>
      )}
      {pendingChoice ? <p>{getResolutionConfirmation(conflict, pendingChoice)}</p> : null}
    </div>
  );
};
