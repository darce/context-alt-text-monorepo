import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import type { UseQueryResult } from '@tanstack/react-query';

import type { AuditEvent } from '../../api/recognition';
import { AUDIT_PAGE_SIZE, type RetentionAction } from './useRetentionPageState';
import { EmptyState, EmptyStateVariant } from '../../components/ui/EmptyState';

interface AuditLogResponse {
  items: AuditEvent[];
  total: number;
}

const formatTimestamp = (value: string | null | undefined): string =>
  value ? new Date(value).toLocaleString() : __('Never', 'alt-context');

const summarizeAuditPayload = (event: AuditEvent): string => {
  const entries = Object.entries(event.payload ?? {}).filter(([, value]) => value !== null && value !== '');
  if (entries.length === 0) {
    return __('No payload details recorded.', 'alt-context');
  }

  return entries
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(' \u00b7 ');
};

export { formatTimestamp };

/* ------------------------------------------------------------------ */
/*  Recent Audit Events                                                */
/* ------------------------------------------------------------------ */

interface RecentAuditEventsProps {
  events: AuditEvent[];
  onRefresh: () => void;
}

export const RecentAuditEvents = ({ events, onRefresh }: RecentAuditEventsProps): React.JSX.Element => (
  <section className="acx-dashboard__panel acx-retention__panel acx-retention__panel--wide">
    <div className="acx-retention__panel-header">
      <h2 id="retention-audit-history">{__('Recent audit events', 'alt-context')}</h2>
      <span className="acx-retention__detail">{__('Showing the five most recent audit events.', 'alt-context')}</span>
    </div>
    {events.length === 0 ? (
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading={__('No audit events recorded yet.', 'alt-context')}
        body={__('Refresh after a data-retention action to see its audit event.', 'alt-context')}
        action={{ label: __('Refresh audit events', 'alt-context'), onClick: onRefresh }}
        headingLevel={3}
        announceState={false}
      />
    ) : (
      <ol className="acx-retention__timeline">
        {events.map((event) => (
          <li key={event.id} className="acx-retention__timeline-item">
            <div className="acx-retention__timeline-heading">
              <strong>{event.event_type}</strong>
              <span>{formatTimestamp(event.created_at)}</span>
            </div>
            <p>{sprintf(__('Actor: %1$s \u00b7 Result: %2$s', 'alt-context'), event.actor, event.result_status)}</p>
            <p>{summarizeAuditPayload(event)}</p>
          </li>
        ))}
      </ol>
    )}
  </section>
);

/* ------------------------------------------------------------------ */
/*  Full Audit Log                                                     */
/* ------------------------------------------------------------------ */

interface FullAuditLogProps {
  auditQuery: UseQueryResult<AuditLogResponse, Error>;
  auditPage: number;
  dispatch: React.Dispatch<RetentionAction>;
}

export const FullAuditLog = ({ auditQuery, auditPage, dispatch }: FullAuditLogProps): React.JSX.Element => (
  <section className="acx-dashboard__panel acx-retention__panel acx-retention__panel--wide">
    <div className="acx-retention__panel-header">
      <h2>{__('Full audit log', 'alt-context')}</h2>
      {auditQuery.data && (
        <span className="acx-retention__detail">
          {sprintf(
            __('%1$d\u2013%2$d of %3$d events', 'alt-context'),
            auditPage * AUDIT_PAGE_SIZE + 1,
            Math.min((auditPage + 1) * AUDIT_PAGE_SIZE, auditQuery.data.total),
            auditQuery.data.total,
          )}
        </span>
      )}
    </div>
    {auditQuery.isLoading && <p>{__('Loading audit log\u2026', 'alt-context')}</p>}
    {auditQuery.isError && (
      <EmptyState
        variant={EmptyStateVariant.UNAVAILABLE}
        heading={__('Audit log unavailable', 'alt-context')}
        body={__('The audit log could not be loaded. Try again.', 'alt-context')}
        action={{ label: __('Retry audit log', 'alt-context'), onClick: () => void auditQuery.refetch() }}
        headingLevel={3}
        announceState={false}
      />
    )}
    {auditQuery.data?.items.length === 0 && (
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading={__('No audit events recorded yet.', 'alt-context')}
        body={__('Refresh after a data-retention action to see its audit event.', 'alt-context')}
        action={{ label: __('Refresh audit log', 'alt-context'), onClick: () => void auditQuery.refetch() }}
        headingLevel={3}
        announceState={false}
      />
    )}
    {auditQuery.data && auditQuery.data.items.length > 0 && (
      <ol className="acx-retention__timeline">
        {auditQuery.data.items.map((event) => (
          <li key={event.id} className="acx-retention__timeline-item">
            <div className="acx-retention__timeline-heading">
              <strong>{event.event_type}</strong>
              <span>{formatTimestamp(event.created_at)}</span>
            </div>
            <p>{sprintf(__('Actor: %1$s \u00b7 Result: %2$s', 'alt-context'), event.actor, event.result_status)}</p>
            <p>{summarizeAuditPayload(event)}</p>
          </li>
        ))}
      </ol>
    )}
    {auditQuery.data && auditQuery.data.total > AUDIT_PAGE_SIZE && (
      <div className="acx-retention__pagination">
        <button
          type="button"
          className="acx-button acx-button--secondary"
          disabled={auditPage === 0}
          onClick={() => dispatch({ type: 'SET_AUDIT_PAGE', page: auditPage - 1 })}
        >
          {__('Previous', 'alt-context')}
        </button>
        <button
          type="button"
          className="acx-button acx-button--secondary"
          disabled={(auditPage + 1) * AUDIT_PAGE_SIZE >= auditQuery.data.total}
          onClick={() => dispatch({ type: 'SET_AUDIT_PAGE', page: auditPage + 1 })}
        >
          {__('Next', 'alt-context')}
        </button>
      </div>
    )}
  </section>
);
