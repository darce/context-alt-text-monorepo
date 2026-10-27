import { AlertTriangle, CircleHelp, Loader2, RefreshCw, Wallet, type LucideIcon } from 'lucide-react';
import { __, _n, sprintf } from '@wordpress/i18n';

import {
  readAccountUsageUrl,
  TENANT_USAGE_AUTHORITATIVE_SOURCE,
  TENANT_USAGE_STATUS,
  type TenantUsage,
} from '../../api/usageApi';
import { useTenantUsage } from '../../hooks/useTenantUsage';
import { formatHostCalendarDay, formatHostCount, readHostUiLocale } from '../../utils/hostLocale';

export const USAGE_BALANCE_STATE = {
  LOADING: 'loading',
  READY: 'ready',
  UPDATING: 'updating',
  UNAVAILABLE: 'unavailable',
  ACCOUNT_HOLD: 'account-hold',
} as const;

export type UsageBalanceState = (typeof USAGE_BALANCE_STATE)[keyof typeof USAGE_BALANCE_STATE];

interface UsageBalancePresentation {
  state: UsageBalanceState;
  Icon: LucideIcon;
  text: string;
  spin?: boolean;
}

const unavailablePresentation = (): UsageBalancePresentation => ({
  state: USAGE_BALANCE_STATE.UNAVAILABLE,
  Icon: CircleHelp,
  text: __('Balance unavailable', 'alt-context'),
});

const accountHold = (text: string): UsageBalancePresentation => ({
  state: USAGE_BALANCE_STATE.ACCOUNT_HOLD,
  Icon: AlertTriangle,
  text,
});

const presentUsage = (usage: TenantUsage, uiLocale: string | null): UsageBalancePresentation => {
  switch (usage.status) {
    case TENANT_USAGE_STATUS.PAST_DUE:
      return accountHold(__('Payment past due', 'alt-context'));
    case TENANT_USAGE_STATUS.EXPIRED:
      return accountHold(__('Plan expired', 'alt-context'));
    case TENANT_USAGE_STATUS.REVOKED:
      return accountHold(__('Access revoked', 'alt-context'));
    case TENANT_USAGE_STATUS.BETA_ACTIVE:
    case TENANT_USAGE_STATUS.PAID_ACTIVE:
    case null:
      break;
    default: {
      const unreachable: never = usage.status;
      return unreachable;
    }
  }

  // The service is the one authority: an unknown count is shown as unknown,
  // never derived from used/reserved [DATA-14].
  const { remaining, allowance } = usage;
  if (remaining === null || allowance === null) {
    return unavailablePresentation();
  }
  const left = formatHostCount(remaining, uiLocale);
  const total = formatHostCount(allowance, uiLocale);
  const resets = formatHostCalendarDay(usage.period_end, uiLocale);

  if (usage.data_source === TENANT_USAGE_AUTHORITATIVE_SOURCE) {
    return {
      state: USAGE_BALANCE_STATE.READY,
      Icon: Wallet,
      text: sprintf(
        _n(
          '%1$s of %2$s credit left · resets %3$s',
          '%1$s of %2$s credits left · resets %3$s',
          allowance,
          'alt-context',
        ),
        left,
        total,
        resets,
      ),
    };
  }
  return {
    state: USAGE_BALANCE_STATE.UPDATING,
    Icon: RefreshCw,
    text: sprintf(
      _n(
        '%1$s of %2$s credit left · resets %3$s · updating',
        '%1$s of %2$s credits left · resets %3$s · updating',
        allowance,
        'alt-context',
      ),
      left,
      total,
      resets,
    ),
  };
};

/**
 * Compact read-only balance beside Describe (ADR-014). It never gates Describe
 * [rg-003] and offers no retry: server admission decides whether a run starts.
 * Local site caps live in Settings; this links to the one Usage & billing home
 * [NAV-05].
 */
export const UsageBalanceChip = (): React.JSX.Element => {
  const usage = useTenantUsage();
  const accountUsageUrl = readAccountUsageUrl();
  const { state, Icon, text, spin } = usage.isError
    ? unavailablePresentation()
    : usage.data === undefined
      ? {
          state: USAGE_BALANCE_STATE.LOADING,
          Icon: Loader2,
          text: __('Checking balance…', 'alt-context'),
          spin: true,
        }
      : presentUsage(usage.data, readHostUiLocale());

  return (
    <p
      className="acx-media-selection__bulk-describe-disclosure acx-usage-balance-chip"
      data-testid="acx-usage-balance-chip"
      data-state={state}
    >
      {/*
        [A11Y-21] One polite region, mounted from the first (loading) render, so
        each settle or refresh of the balance is announced. The Usage & billing
        link stays outside it and is not re-announced.
      */}
      <span role="status" aria-live="polite">
        <Icon
          className={spin ? 'acx-media-selection__bulk-describe-spin' : undefined}
          aria-hidden="true"
          size={16}
        />{' '}
        {text}
      </span>
      {accountUsageUrl !== '' ? (
        <>
          {' · '}
          <a href={accountUsageUrl} target="_blank" rel="noopener noreferrer">
            {__('Usage & billing', 'alt-context')}
            <span className="screen-reader-text"> {__('(opens in a new tab)', 'alt-context')}</span>
          </a>
        </>
      ) : null}
    </p>
  );
};
