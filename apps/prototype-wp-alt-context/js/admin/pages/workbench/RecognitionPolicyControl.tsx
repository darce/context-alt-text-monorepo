import React, { useEffect, useId, useRef, useState } from 'react';
import { __ } from '@wordpress/i18n';
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';

import { getConfig, type RecognitionPolicyBootstrap } from '../../api/config';
import { queryKeys } from '../../api/queryKeys';
import { fetchSettings, saveSettings, SettingsSaveResult, type SettingsResponse } from '../../api/settingsApi';
import { AuthExpiredError, HTTPError } from '../../utils/http';
import { useFocusPark } from './identity-clusters/useFocusPark';

/**
 * WBRC-1: the site's facial recognition policy beside the Workbench scan controls
 * [NAV-06]. Off until an administrator opts in ([SECD-12]); turning it off is the
 * same one action as turning it on ([SECD-08]). The only store is the Settings
 * endpoint and its shared `queryKeys.settings.all` cache; manage_options is
 * enforced by the server on every request ([WP-03]).
 */
export const RECOGNITION_POLICY_COPY = {
  label: __('Facial recognition', 'alt-context'),
  on: __('On', 'alt-context'),
  off: __('Off', 'alt-context'),
  unknown: __('Unknown', 'alt-context'),
  checking: __('Checking…', 'alt-context'),
  scope: __('Site-wide', 'alt-context'),
  // [HAI-05] says what the AI does and how far a change reaches; [CLM-03] it
  // promises no deletion or cancellation, because toggling performs neither.
  explain: __(
    'When on, scans use AI to find faces and suggest who they are. A change applies to scans and descriptions started afterwards; turning it off does not delete people already found or cancel work already running.',
    'alt-context',
  ),
  enable: __('Enable facial recognition', 'alt-context'),
  disable: __('Disable facial recognition', 'alt-context'),
  retry: __('Retry reading policy', 'alt-context'),
  saving: __('Saving…', 'alt-context'),
  reading: __('Reading…', 'alt-context'),
  savingStatus: __('Saving the change…', 'alt-context'),
  readingStatus: __('Reading the setting back from the site…', 'alt-context'),
  confirmedOn: __('Saved and verified. Facial recognition is now on.', 'alt-context'),
  confirmedOff: __('Saved and verified. Facial recognition is now off.', 'alt-context'),
  readFailed: __('Could not read the current setting. Check your connection, then retry.', 'alt-context'),
  staleNote: __('Could not re-check the setting just now, so this shows the last value read.', 'alt-context'),
  rejectedOn: __('The site did not save this change, so facial recognition is still on. You can try again.', 'alt-context'),
  rejectedOff: __('The site did not save this change, so facial recognition is still off. You can try again.', 'alt-context'),
  sessionExpired: __('Your session has expired, so the change was not saved. Reload the page to sign in again.', 'alt-context'),
  acceptedReadFailed: __('The site accepted the change, but reading it back failed. Retry reading before changing it again.', 'alt-context'),
  acceptedMismatchOn: __('The site accepted the change, but now reports facial recognition is on. It may have been changed elsewhere; retry reading to confirm.', 'alt-context'),
  acceptedMismatchOff: __('The site accepted the change, but now reports facial recognition is off. It may have been changed elsewhere; retry reading to confirm.', 'alt-context'),
  uncertainReadFailed: __('Could not confirm whether the change was saved. Retry reading to see the current setting.', 'alt-context'),
  unconfirmedRead: __('Could not confirm the save result. The current setting has been read from the site.', 'alt-context'),
  notAppliedOn: __('The change is not in effect: the site reports facial recognition is on.', 'alt-context'),
  notAppliedOff: __('The change is not in effect: the site reports facial recognition is off.', 'alt-context'),
  accessLost: __('Your account can no longer change site settings. Ask a site administrator to change this.', 'alt-context'),
  denied: __('Only site administrators can change this setting.', 'alt-context'),
  unknownCapability: __('Could not confirm that your account can change this setting. Reload the page; if this continues, ask a site administrator.', 'alt-context'),
  asOfPageLoad: __('Shown as of when this page loaded.', 'alt-context'),
  asOfLastRead: __('Shown as last read from the site.', 'alt-context'),
} as const;

const COPY = RECOGNITION_POLICY_COPY;

/** sr-007: what the control has learned about the latest change. */
const OUTCOME = {
  NONE: 'none',
  /** A read taken after the write returned the requested value. */
  CONFIRMED: 'confirmed',
  /** A fresh read is current, but the write never had a valid field acknowledgement. */
  OBSERVED: 'observed',
  /** The site refused the write or reported the field failed: nothing changed. */
  REJECTED: 'rejected',
  SESSION_EXPIRED: 'session_expired',
  /** A read after an uncertain write, or an explicit re-read, disagrees: accept it as current. */
  NOT_APPLIED: 'not_applied',
  /** No read after the write has agreed yet: offer only another read, never the write again. */
  UNVERIFIED: 'unverified',
  ACCESS_LOST: 'access_lost',
} as const;

type Outcome =
  | { kind: typeof OUTCOME.NONE | typeof OUTCOME.SESSION_EXPIRED | typeof OUTCOME.ACCESS_LOST }
  | { kind: typeof OUTCOME.CONFIRMED | typeof OUTCOME.OBSERVED | typeof OUTCOME.REJECTED | typeof OUTCOME.NOT_APPLIED; enabled: boolean }
  | { kind: typeof OUTCOME.UNVERIFIED; desired: boolean; acknowledged: boolean };

const NO_OUTCOME: Outcome = { kind: OUTCOME.NONE };

/** A read the control requested itself; `null` enabled means the read failed. */
type FreshRead = { forbidden: true } | { forbidden: false; enabled: boolean | null };

const WRITE = { ACKNOWLEDGED: 'acknowledged', REJECTED: 'rejected', UNCERTAIN: 'uncertain' } as const;
type Write = (typeof WRITE)[keyof typeof WRITE];

const POLICY_FIELD = 'recognition_enabled';

const isForbidden = (error: unknown): boolean => error instanceof HTTPError && error.status === 403;

const readEnabled = (settings: SettingsResponse | undefined): boolean | null => {
  const enabled: unknown = settings?.recognition_enabled;
  return typeof enabled === 'boolean' ? enabled : null;
};

/**
 * SettingsController::save_settings answers HTTP 200 whether or not the field
 * persisted, so status alone is not success. The body is unvalidated JSON.
 */
const classifyWrite = (response: unknown): Write => {
  const body = response !== null && typeof response === 'object' ? (response as Record<string, unknown>) : {};
  const failed = body.failed === undefined ? [] : body.failed;
  if (!Array.isArray(body.saved) || !Array.isArray(failed)
    || !body.saved.every((field: unknown) => typeof field === 'string')
    || !failed.every((field: unknown) => typeof field === 'string')) {
    return WRITE.UNCERTAIN;
  }
  const saved = body.saved.includes(POLICY_FIELD);
  const refused = failed.includes(POLICY_FIELD);
  if (body.result === SettingsSaveResult.OK && saved && failed.length === 0) {
    return WRITE.ACKNOWLEDGED;
  }
  const failedResult = body.result === SettingsSaveResult.PARTIAL || body.result === SettingsSaveResult.ERROR;
  return failedResult && refused && !saved ? WRITE.REJECTED : WRITE.UNCERTAIN;
};

/**
 * Drop the cached value, then read again: once a write may have landed, the old
 * value is stale for every reader of the shared key, not just this control.
 */
const readFresh = async (queryClient: QueryClient): Promise<FreshRead> => {
  await queryClient.resetQueries({ queryKey: queryKeys.settings.all, exact: true });
  const state = queryClient.getQueryState<SettingsResponse>(queryKeys.settings.all);
  if (state?.status === 'error' && isForbidden(state.error)) {
    return { forbidden: true };
  }
  return { forbidden: false, enabled: state?.status === 'success' ? readEnabled(state.data) : null };
};

/**
 * [FORM-08] Only a read taken after the write may confirm it. An acknowledged
 * write whose first read fails or disagrees stays unverified (CURUX 19129: never
 * resend an acknowledged write); a later explicit read is the current state.
 */
const settle = (read: FreshRead, desired: boolean, acknowledged: boolean, firstRead: boolean): Outcome => {
  if (read.forbidden) {
    return { kind: OUTCOME.ACCESS_LOST };
  }
  if (read.enabled === desired) {
    return { kind: acknowledged ? OUTCOME.CONFIRMED : OUTCOME.OBSERVED, enabled: desired };
  }
  if (read.enabled === null || (acknowledged && firstRead)) {
    return { kind: OUTCOME.UNVERIFIED, desired, acknowledged };
  }
  return { kind: OUTCOME.NOT_APPLIED, enabled: read.enabled };
};

/** [FORM-05] The error beside the control; value-bearing messages drop once a newer read disagrees. */
const alertFor = (outcome: Outcome, enabled: boolean | null, readFailed: boolean): string | null => {
  switch (outcome.kind) {
    case OUTCOME.OBSERVED:
      return enabled === outcome.enabled ? COPY.unconfirmedRead : null;
    case OUTCOME.REJECTED:
      return enabled === outcome.enabled ? (enabled ? COPY.rejectedOn : COPY.rejectedOff) : null;
    case OUTCOME.NOT_APPLIED:
      return enabled === outcome.enabled ? (enabled ? COPY.notAppliedOn : COPY.notAppliedOff) : null;
    case OUTCOME.SESSION_EXPIRED:
      return COPY.sessionExpired;
    case OUTCOME.UNVERIFIED:
      if (!outcome.acknowledged) {
        return COPY.uncertainReadFailed;
      }
      if (enabled === null) {
        return COPY.acceptedReadFailed;
      }
      return enabled ? COPY.acceptedMismatchOn : COPY.acceptedMismatchOff;
    case OUTCOME.NONE:
    case OUTCOME.CONFIRMED:
    case OUTCOME.ACCESS_LOST:
      return enabled === null && readFailed ? COPY.readFailed : null;
    default: {
      const unreachable: never = outcome;
      return unreachable;
    }
  }
};

const stateLabel = (enabled: boolean | null, unknown: boolean): string => {
  if (enabled !== null) {
    return enabled ? COPY.on : COPY.off;
  }
  return unknown ? COPY.unknown : COPY.checking;
};

/**
 * Page-load snapshot. Anything that keeps it from being read (no localized
 * bootstrap in an isolated render) leaves it unknown: never Off, never a grant.
 */
const readPageLoadPolicy = (): RecognitionPolicyBootstrap => {
  try {
    const { enabled, canManage } = getConfig().recognitionPolicy;
    return { enabled, canManage };
  } catch {
    return { enabled: null, canManage: null };
  }
};

interface PolicyFrameProps {
  state: string;
  /** Present on the administrator frame, which parks focus while an action is busy. */
  frameRef?: React.Ref<HTMLDivElement>;
  children: React.ReactNode;
}

const PolicyFrame = ({ state, frameRef, children }: PolicyFrameProps): React.JSX.Element => {
  const labelId = useId();
  return (
    <div
      ref={frameRef}
      className="acx-recognition-policy"
      role="group"
      aria-labelledby={labelId}
      tabIndex={frameRef ? -1 : undefined}
    >
      <p className="acx-recognition-policy__state">
        <span id={labelId}>{COPY.label}</span>: <strong>{state}</strong> · <span>{COPY.scope}</span>
      </p>
      <p className="description">{COPY.explain}</p>
      {children}
    </div>
  );
};

const ErrorNotice = ({ message }: { message: string }): React.JSX.Element => (
  <p className="notice inline notice-error" role="alert">
    <AlertTriangle aria-hidden="true" size={16} /> {message}
  </p>
);

/**
 * No live reads for an administrator who lost access, and none at all without
 * a confirmed manage capability: Settings exposes more than this one boolean.
 */
const ReadOnlyNote = ({ note, asOf, asError }: { note: string; asOf: string; asError: boolean }): React.JSX.Element => (
  <>
    {asError ? <ErrorNotice message={note} /> : <p>{note}</p>}
    <p className="description">{asOf}</p>
  </>
);

const ManagedRecognitionPolicy = ({ pageLoad }: { pageLoad: RecognitionPolicyBootstrap }): React.JSX.Element => {
  const queryClient = useQueryClient();
  const [outcome, setOutcome] = useState<Outcome>(NO_OUTCOME);
  const [reading, setReading] = useState(false);
  const frameRef = useRef<HTMLDivElement>(null);
  const actionRef = useRef<HTMLButtonElement>(null);
  const wasBusy = useRef(false);

  const settingsQuery = useQuery<SettingsResponse>({
    queryKey: queryKeys.settings.all,
    queryFn: fetchSettings,
    retry: false,
    // A 403 is final for this page: stop reading, as well as writing.
    enabled: (query) => outcome.kind !== OUTCOME.ACCESS_LOST && !isForbidden(query.state.error),
    // Re-read on entry and on return to the window so a change made in Settings is not stale,
    // except while an unverified write waits for the operator's explicit read.
    refetchOnMount: 'always',
    refetchOnWindowFocus: outcome.kind === OUTCOME.UNVERIFIED ? false : 'always',
  });

  const read = async (settleRead: (fresh: FreshRead) => Outcome): Promise<void> => {
    setReading(true);
    try {
      setOutcome(settleRead(await readFresh(queryClient)));
    } catch {
      setOutcome(settleRead({ forbidden: false, enabled: null }));
    } finally {
      setReading(false);
    }
  };

  const save = useMutation({
    // The payload is this one field: never the URL, key, or naming settings.
    mutationFn: (desired: boolean) => saveSettings({ recognition_enabled: desired }),
    onMutate: () => setOutcome(NO_OUTCOME),
    onSuccess: async (response, desired) => {
      const write = classifyWrite(response);
      if (write === WRITE.REJECTED) {
        setOutcome({ kind: OUTCOME.REJECTED, enabled: !desired });
        return;
      }
      await read((fresh) => settle(fresh, desired, write === WRITE.ACKNOWLEDGED, true));
    },
    onError: async (error, desired) => {
      if (isForbidden(error)) {
        setOutcome({ kind: OUTCOME.ACCESS_LOST });
      } else if (error instanceof AuthExpiredError) {
        setOutcome({ kind: OUTCOME.SESSION_EXPIRED });
      } else if (error instanceof HTTPError && error.status >= 400 && error.status < 500) {
        setOutcome({ kind: OUTCOME.REJECTED, enabled: !desired });
      } else {
        // 5xx, timeout, transport or an unreadable body: the write may have landed.
        await read((fresh) => settle(fresh, desired, false, true));
      }
    },
  });

  const busy = save.isPending || reading;
  useFocusPark(busy, frameRef);
  // After a busy spell, hand focus parked on the frame (or stranded) back to the action.
  useEffect(() => {
    if (busy) {
      wasBusy.current = true;
      // Disabled buttons can retain focus until the browser processes blur.
      // Park our own action immediately, without taking focus from elsewhere.
      if (document.activeElement === actionRef.current) {
        frameRef.current?.focus();
      }
      return;
    }
    if (!wasBusy.current) {
      return;
    }
    wasBusy.current = false;
    const frame = frameRef.current;
    const active = document.activeElement;
    if (frame && (active === frame || active === document.body || !active?.isConnected)) {
      (actionRef.current ?? frame).focus();
    }
  }, [busy]);

  const enabled = readEnabled(settingsQuery.data);
  const readFailed = settingsQuery.isError;
  const unverified = outcome.kind === OUTCOME.UNVERIFIED;

  if (outcome.kind === OUTCOME.ACCESS_LOST || isForbidden(settingsQuery.error)) {
    return (
      <PolicyFrame state={stateLabel(enabled ?? pageLoad.enabled, true)} frameRef={frameRef}>
        <ReadOnlyNote note={COPY.accessLost} asOf={enabled === null ? COPY.asOfPageLoad : COPY.asOfLastRead} asError />
      </PolicyFrame>
    );
  }

  const retryRead = (): void => {
    void read((fresh) => {
      if (outcome.kind === OUTCOME.UNVERIFIED) {
        return settle(fresh, outcome.desired, outcome.acknowledged, false);
      }
      return fresh.forbidden ? { kind: OUTCOME.ACCESS_LOST } : NO_OUTCOME;
    });
  };

  let action: { label: string; onClick?: () => void } | null = null;
  if (busy) {
    action = { label: reading ? COPY.reading : COPY.saving };
  } else if (unverified || (enabled === null && readFailed)) {
    action = { label: COPY.retry, onClick: retryRead };
  } else if (enabled !== null) {
    action = { label: enabled ? COPY.disable : COPY.enable, onClick: () => save.mutate(!enabled) };
  }

  let status = '';
  if (busy) {
    status = reading ? COPY.readingStatus : COPY.savingStatus;
  } else if (enabled !== null && readFailed) {
    status = COPY.staleNote;
  } else if (outcome.kind === OUTCOME.CONFIRMED && enabled === outcome.enabled) {
    status = enabled ? COPY.confirmedOn : COPY.confirmedOff;
  }
  const alert = busy ? null : alertFor(outcome, enabled, readFailed);

  return (
    <PolicyFrame state={stateLabel(enabled, readFailed || unverified)} frameRef={frameRef}>
      {action ? (
        <button
          ref={actionRef}
          type="button"
          className="button button-secondary"
          disabled={busy}
          onClick={action.onClick}
        >
          {action.label}
        </button>
      ) : null}
      <p className="acx-recognition-policy__status" role="status" aria-live="polite">
        {status}
      </p>
      {alert ? <ErrorNotice message={alert} /> : null}
    </PolicyFrame>
  );
};

export const RecognitionPolicyControl = (): React.JSX.Element => {
  const [pageLoad] = useState(readPageLoadPolicy);
  if (pageLoad.canManage === true) {
    return <ManagedRecognitionPolicy pageLoad={pageLoad} />;
  }
  return (
    <PolicyFrame state={stateLabel(pageLoad.enabled, true)}>
      <ReadOnlyNote
        note={pageLoad.canManage === false ? COPY.denied : COPY.unknownCapability}
        asOf={COPY.asOfPageLoad}
        asError={false}
      />
    </PolicyFrame>
  );
};
