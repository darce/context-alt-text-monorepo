/**
 * NameFaceControl (UXW2-3) — one shared naming control for every surface that
 * names a face group: queue card (PersonCommitControl), queue label panel
 * (ClusterLabelingPanel), Library pane (ClusterEditForm).
 *
 * Presentational, inline, keyboard-first, evidence-ranked (extracted from
 * ClusterEditForm). Naming a face always creates/binds a roster person, so the
 * control resolves a single gesture (Enter or the primary button) to:
 * exact roster match → { kind: 'roster', rosterEntryId }; novel name →
 * { kind: 'create', name } (create is the default outcome — PRINCIPLES §6).
 */

import React, { useEffect, useRef } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { ComboboxOption } from '../../../../components/ui/combobox';
import { NAMING_GROUP_SUGGESTED, parseNamingOptionValue } from './buildNamingOptions';
import { ACCENT_PRIMARY_ATTR } from '../mediaFooterCtaState';

export type NameFaceResolution =
  | { readonly kind: 'roster'; readonly rosterEntryId: number; readonly name: string }
  | { readonly kind: 'create'; readonly name: string };

/** Similarity at-or-above this threshold uses the high match-score band. */
const MATCH_BAND_HIGH_THRESHOLD = 0.7;

const optionSource = (option: ComboboxOption): 'person' | 'cluster' | null => {
  const source =
    option.source === 'person' || option.source === 'cluster'
      ? option.source
      : parseNamingOptionValue(String(option.value))?.source;
  return source ?? null;
};

const sourceBadgeLabel = (option: ComboboxOption): string | null => {
  const source = optionSource(option);
  if (source === 'person') {
    return __('Person', 'alt-context');
  }
  // Include source on Suggested and All Labels cluster rows (A11Y-04 / FIX-7).
  if (source === 'cluster') {
    return __('Cluster', 'alt-context');
  }
  return null;
};

/** Max overlay rows; Suggested budget first so persons/All Labels are not starved (FIX-6). */
export const OVERLAY_OPTIONS_LIMIT = 5;
export const OVERLAY_SUGGESTED_BUDGET = 3;

/**
 * Budget overlay rows: up to OVERLAY_SUGGESTED_BUDGET Suggested, remainder from union, total ≤ limit.
 */
export const budgetOverlayOptions = (
  options: readonly ComboboxOption[],
  limit = OVERLAY_OPTIONS_LIMIT,
  suggestedBudget = OVERLAY_SUGGESTED_BUDGET,
): ComboboxOption[] => {
  const suggested: ComboboxOption[] = [];
  const union: ComboboxOption[] = [];
  for (const option of options) {
    if (option.group === NAMING_GROUP_SUGGESTED) {
      suggested.push(option);
    } else {
      union.push(option);
    }
  }
  const suggestedSlice = suggested.slice(0, suggestedBudget);
  const remainder = Math.max(0, limit - suggestedSlice.length);
  return [...suggestedSlice, ...union.slice(0, remainder)];
};

/**
 * Resolve free-typed text against the fed options: an exact case-insensitive
 * person match binds that roster entry; anything else creates a new person.
 */
export const resolveNameFaceInput = (
  options: readonly ComboboxOption[],
  raw: string,
): NameFaceResolution | null => {
  const name = raw.trim();
  if (!name) {
    return null;
  }
  const normalized = name.toLowerCase();
  const person = options.find(
    (option) =>
      optionSource(option) === 'person' && option.label.trim().toLowerCase() === normalized,
  );
  if (person) {
    const parsed = parseNamingOptionValue(String(person.value));
    const rosterEntryId = Number.parseInt(parsed?.id ?? '', 10);
    if (Number.isFinite(rosterEntryId)) {
      return { kind: 'roster', rosterEntryId, name: person.label.trim() };
    }
  }
  return { kind: 'create', name };
};

interface NameFaceControlProps {
  /** Naming options (roster persons ∪ labelled clusters ∪ similarity suggestions). */
  options: readonly ComboboxOption[];
  /** Current input value (controlled). */
  value: string;
  onValueChange: (value: string) => void;
  /** Single-gesture commit: Enter or the primary button. */
  onCommit: (resolution: NameFaceResolution) => void;
  /** Row ✓ override; default resolves person rows to a roster commit, others fill the input. */
  onOptionConfirm?: (option: ComboboxOption) => void;
  /** Row ✕ for pending suggestions. */
  onRejectSuggestion?: (suggestionId: string) => void;
  /** Escape / Cancel. Cancel button renders only when this is provided. */
  onCancel?: () => void;
  isPending?: boolean;
  disabled?: boolean;
  commitLabel: string;
  pendingLabel?: string;
  placeholder?: string;
  ariaLabel: string;
  inputId?: string;
  autoFocus?: boolean;
  /** §7 single accent primary marker + accent chrome on the commit button (COL-03). */
  accentPrimary?: boolean;
  /** Override class for the commit button (surface-specific chrome, e.g. WP button classes). */
  commitButtonClassName?: string;
  /** Extra wrapper class (surface-specific chrome). */
  className?: string;
  /** Class prefix for inner elements; defaults to the shared acx-name-face surface. */
  classPrefix?: string;
  /** Optional hint rendered inside the input wrapper; described by the input. */
  hint?: React.ReactNode;
  hintId?: string;
}

export const NameFaceControl = ({
  options,
  value,
  onValueChange,
  onCommit,
  onOptionConfirm,
  onRejectSuggestion,
  onCancel,
  isPending = false,
  disabled = false,
  commitLabel,
  pendingLabel,
  placeholder,
  ariaLabel,
  inputId,
  autoFocus = true,
  accentPrimary = false,
  commitButtonClassName,
  className,
  classPrefix = 'acx-name-face',
  hint,
  hintId,
}: NameFaceControlProps): React.JSX.Element => {
  const inputRef = useRef<HTMLInputElement>(null);
  const isDisabled = isPending || disabled;

  useEffect(() => {
    if (autoFocus) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
    // Autofocus once on mount only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const displayedOptions = React.useMemo(() => budgetOverlayOptions(options), [options]);

  const commitButtonLabel = isPending && pendingLabel ? pendingLabel : commitLabel;

  // Live-region status (A11Y-21): announce save progress/success at the field (PERC-05 fovea).
  const resultCountAnnouncement = React.useMemo(() => {
    if (isPending) {
      return commitButtonLabel;
    }
    return sprintf(
      /* translators: %d: number of naming suggestions shown */
      __('%d naming options', 'alt-context'),
      displayedOptions.length,
    );
  }, [displayedOptions.length, isPending, commitButtonLabel]);

  const commitValue = React.useCallback(
    (raw: string) => {
      const resolution = resolveNameFaceInput(options, raw);
      if (resolution) {
        onCommit(resolution);
      }
    },
    [options, onCommit],
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitValue(value);
    } else if (e.key === 'Escape') {
      onCancel?.();
    }
  };

  const handleSuggestionSelect = React.useCallback(
    (label: string) => () => {
      onValueChange(label);
    },
    [onValueChange],
  );

  const handleConfirmOptionClick = React.useCallback(
    (option: ComboboxOption) => (event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      if (onOptionConfirm) {
        onOptionConfirm(option);
        return;
      }
      if (optionSource(option) === 'person') {
        commitValue(option.label);
        return;
      }
      onValueChange(option.label);
    },
    [onOptionConfirm, commitValue, onValueChange],
  );

  const handleRejectSuggestionClick = React.useCallback(
    (suggestionId: string) => (event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      onRejectSuggestion?.(suggestionId);
    },
    [onRejectSuggestion],
  );

  return (
    <div className={className ?? classPrefix}>
      <div className={`${classPrefix}__input-wrapper`}>
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={displayedOptions.length > 0}
          aria-haspopup="listbox"
          className={`${classPrefix}__label-input`}
          id={inputId}
          value={value}
          onChange={(e) => onValueChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder ?? __('Enter a name…', 'alt-context')}
          disabled={isDisabled}
          aria-label={ariaLabel}
          aria-describedby={hint ? hintId : undefined}
        />

        {displayedOptions.length > 0 && !isPending && (
          <div className={`${classPrefix}__suggestions-overlay`}>
            <div className={`${classPrefix}__suggestions-header`}>{__('Suggested', 'alt-context')}</div>
            {displayedOptions.map((option) => (
              <div key={option.value} className={`${classPrefix}__suggestion-row`}>
                <button
                  type="button"
                  className={`${classPrefix}__suggestion-item`}
                  onClick={handleSuggestionSelect(option.label)}
                  title={sprintf(__('Use label "%s"', 'alt-context'), option.label)}
                  aria-label={
                    sourceBadgeLabel(option)
                      ? sprintf(
                          /* translators: 1: person/cluster name, 2: source (Person or Cluster) */
                          __('%1$s (%2$s)', 'alt-context'),
                          option.label,
                          sourceBadgeLabel(option) ?? '',
                        )
                      : option.label
                  }
                >
                  <span className={`${classPrefix}__suggestion-label`}>{option.label}</span>
                  {sourceBadgeLabel(option) && (
                    <span className="acx-badge acx-badge--source" data-source={option.source ?? ''}>
                      {sourceBadgeLabel(option)}
                    </span>
                  )}
                  {option.similarity !== undefined && (
                    <span
                      className={`${classPrefix}__match-score ${
                        (option.similarity as number) >= MATCH_BAND_HIGH_THRESHOLD
                          ? `${classPrefix}__match-score--high`
                          : `${classPrefix}__match-score--medium`
                      }`}
                    >
                      {Math.round((option.similarity as number) * 100)}%{' '}
                      <span className={`${classPrefix}__match-score-band`}>
                        {(option.similarity as number) >= MATCH_BAND_HIGH_THRESHOLD
                          ? __('high', 'alt-context')
                          : __('medium', 'alt-context')}
                      </span>
                    </span>
                  )}
                </button>
                <div className={`${classPrefix}__suggestion-actions`}>
                  <button
                    type="button"
                    className={`${classPrefix}__suggestion-confirm`}
                    onClick={handleConfirmOptionClick(option)}
                    title={__('Confirm match', 'alt-context')}
                    aria-label={__('Confirm match', 'alt-context')}
                  >
                    ✓
                  </button>
                  {!!option.suggestion_id && !!onRejectSuggestion && (
                    <button
                      type="button"
                      className={`${classPrefix}__suggestion-reject`}
                      onClick={handleRejectSuggestionClick(option.suggestion_id as string)}
                      title={__('Reject suggestion', 'alt-context')}
                      aria-label={__('Reject suggestion', 'alt-context')}
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        {hint}
      </div>

      <p className={`${classPrefix}__result-count`} role="status" aria-live="polite">
        {resultCountAnnouncement}
      </p>

      <div className={`${classPrefix}__edit-actions`}>
        <button
          type="button"
          className={commitButtonClassName ?? `${classPrefix}__save`}
          onClick={() => commitValue(value)}
          disabled={isDisabled || !value.trim()}
          {...(accentPrimary ? { [ACCENT_PRIMARY_ATTR]: true } : {})}
        >
          {commitButtonLabel}
        </button>
        {onCancel ? (
          <button type="button" className={`${classPrefix}__cancel`} onClick={onCancel}>
            {__('Cancel', 'alt-context')}
          </button>
        ) : null}
      </div>
    </div>
  );
};
