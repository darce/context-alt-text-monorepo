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

import React, { useEffect, useId, useRef, useState } from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';

import type { ComboboxOption } from '../../../../components/ui/combobox';
import { NAMING_GROUP_SUGGESTED, parseNamingOptionValue } from './buildNamingOptions';
import { ACCENT_PRIMARY_ATTR } from '../mediaFooterCtaState';

export type NameFaceResolution =
  | { readonly kind: 'roster'; readonly rosterEntryId: number; readonly name: string }
  | { readonly kind: 'create'; readonly name: string }
  | { readonly kind: 'ambiguous'; readonly name: string; readonly matches: readonly ComboboxOption[] };

/** Similarity at-or-above this threshold uses the high match-score band. */
const MATCH_BAND_HIGH_THRESHOLD = 0.7;

const LIVE_ANNOUNCE_DEBOUNCE_MS = 400;

export const normalizeNameFaceLabel = (raw: string): string =>
  raw.normalize('NFC').replace(/\s+/g, ' ').trim().toLocaleLowerCase();

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
  if (source === 'cluster') {
    return __('Group', 'alt-context');
  }
  return null;
};

const personMatchesFor = (
  options: readonly ComboboxOption[],
  raw: string,
): ComboboxOption[] => {
  const folded = normalizeNameFaceLabel(raw);
  if (!folded) {
    return [];
  }
  return options.filter(
    (option) => optionSource(option) === 'person' && normalizeNameFaceLabel(option.label) === folded,
  );
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
 * Resolve free-typed text against the FULL fed options (not the display budget):
 * NFC + locale-aware fold + whitespace collapse; unique person match binds;
 * two-or-more folded matches force an explicit choice; anything else creates.
 */
export const resolveNameFaceInput = (
  options: readonly ComboboxOption[],
  raw: string,
): NameFaceResolution | null => {
  const name = raw.normalize('NFC').replace(/\s+/g, ' ').trim();
  if (!name) {
    return null;
  }
  const matches = personMatchesFor(options, name);
  if (matches.length > 1) {
    return { kind: 'ambiguous', name, matches };
  }
  if (matches.length === 1) {
    const person = matches[0];
    const parsed = parseNamingOptionValue(String(person.value));
    const rosterEntryId = Number.parseInt(parsed?.id ?? '', 10);
    if (Number.isFinite(rosterEntryId)) {
      return { kind: 'roster', rosterEntryId, name: person.label.trim() };
    }
  }
  return { kind: 'create', name };
};

const highlightMatch = (label: string, query: string): React.ReactNode => {
  const nfcLabel = label.normalize('NFC');
  const nfcQuery = query.normalize('NFC').replace(/\s+/g, ' ').trim();
  if (!nfcQuery) {
    return nfcLabel;
  }
  const escaped = nfcQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');
  const match = new RegExp(escaped, 'i').exec(nfcLabel);
  if (match?.index == null) {
    return nfcLabel;
  }
  const start = match.index;
  const end = start + match[0].length;
  return (
    <>
      {nfcLabel.slice(0, start)}
      <mark className="acx-name-face__match-highlight">{nfcLabel.slice(start, end)}</mark>
      {nfcLabel.slice(end)}
    </>
  );
};

const matchingOptionsFor = (
  options: readonly ComboboxOption[],
  value: string,
): ComboboxOption[] => {
  const folded = normalizeNameFaceLabel(value);
  if (!folded) {
    return [...options];
  }
  return options.filter((option) => normalizeNameFaceLabel(option.label).includes(folded));
};

interface NameFaceControlProps {
  /** Naming options (roster persons ∪ labelled groups ∪ similarity suggestions). */
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
  /** Roster/options still loading — announced, input disabled, create path blocked. */
  isLoading?: boolean;
  /** Override for the input's disabled state (defaults to isPending || isLoading). */
  inputDisabled?: boolean;
  /** Suppress the built-in result-count live region (surface renders its own). */
  hideStatusAnnouncement?: boolean;
  commitLabel: string;
  pendingLabel?: string;
  /**
   * Derive Save as / Create person from resolveNameFaceInput. Unset keeps
   * commitLabel so Library and labeling-panel callers stay on their static copy.
   */
  previewCommit?: boolean;
  placeholder?: string;
  /** Restored Combobox prop: preferred placeholder when searching. */
  searchPlaceholder?: string;
  /** Optional; omitted when a visible <label htmlFor> already names the input. */
  ariaLabel?: string;
  /** Visible label associated via htmlFor={inputId}. */
  visibleLabel?: string;
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
  /** Overlay heading; Library vs review queue want different words. */
  suggestionsHeader?: string;
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
  isLoading = false,
  inputDisabled,
  hideStatusAnnouncement = false,
  commitLabel,
  pendingLabel,
  previewCommit = false,
  placeholder,
  searchPlaceholder,
  ariaLabel,
  visibleLabel,
  inputId,
  autoFocus = true,
  accentPrimary = false,
  commitButtonClassName,
  className,
  classPrefix = 'acx-name-face',
  suggestionsHeader,
  hint,
  hintId,
}: NameFaceControlProps): React.JSX.Element => {
  const inputRef = useRef<HTMLInputElement>(null);
  const reactId = useId();
  const listboxId = `acx-name-face-listbox-${reactId}`;
  const [activeIndex, setActiveIndex] = useState(-1);
  const [announcedTotal, setAnnouncedTotal] = useState<number | null>(null);
  const [chosenOptionValue, setChosenOptionValue] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(true);
  const isDisabled = isPending || disabled || isLoading;
  const isInputDisabled = disabled || isLoading || (inputDisabled ?? isPending);

  useEffect(() => {
    if (autoFocus) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
    // Autofocus once on mount only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const matchingOptions = React.useMemo(() => matchingOptionsFor(options, value), [options, value]);
  const displayedOptions = React.useMemo(
    () => budgetOverlayOptions(matchingOptions),
    [matchingOptions],
  );
  const matchTotal = matchingOptions.length;
  const overlayOpen = listOpen && displayedOptions.length > 0 && !isPending && !isLoading;

  useEffect(() => {
    setActiveIndex(-1);
    setChosenOptionValue(null);
  }, [value, matchTotal]);

  useEffect(() => {
    if (isPending || isLoading) {
      setAnnouncedTotal(null);
      return;
    }
    const timer = window.setTimeout(() => {
      setAnnouncedTotal(matchTotal);
    }, LIVE_ANNOUNCE_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [matchTotal, isPending, isLoading]);

  const commitResolution = React.useMemo(
    () => resolveNameFaceInput(options, value),
    [options, value],
  );

  const commitButtonLabel = React.useMemo(() => {
    if (isPending && pendingLabel) {
      return pendingLabel;
    }
    // overlayOpen is false while pending; keep the highlighted row so
    // pendingLabel is the only thing that beats the active-row preview.
    const activeOption =
      listOpen && !isLoading && activeIndex >= 0 ? displayedOptions[activeIndex] : undefined;
    const resolution =
      previewCommit && activeOption
        ? resolveNameFaceInput(options, activeOption.label)
        : commitResolution;
    if (previewCommit && resolution?.kind === 'roster') {
      return sprintf(
        /* translators: %s: existing roster person label the commit will bind */
        __('Save as %s', 'alt-context'),
        resolution.name,
      );
    }
    if (previewCommit && resolution?.kind === 'create') {
      return sprintf(
        /* translators: %s: typed name the commit will create as a new person */
        __('Create person "%s"', 'alt-context'),
        resolution.name,
      );
    }
    return commitLabel;
  }, [
    isPending,
    pendingLabel,
    previewCommit,
    commitResolution,
    commitLabel,
    listOpen,
    isLoading,
    activeIndex,
    displayedOptions,
    options,
  ]);

  const ambiguousMatches = React.useMemo(
    () => (value.trim() ? personMatchesFor(options, value) : []),
    [options, value],
  );
  const isAmbiguous = ambiguousMatches.length > 1 && chosenOptionValue === null;

  const resultCountAnnouncement = React.useMemo(() => {
    if (isLoading) {
      return __('Loading people…', 'alt-context');
    }
    if (isPending) {
      return commitButtonLabel;
    }
    if (isAmbiguous) {
      return __('Multiple people match. Choose one.', 'alt-context');
    }
    if (announcedTotal === null) {
      return '';
    }
    return sprintf(
      /* translators: %d: number of naming matches */
      _n('%d naming option', '%d naming options', announcedTotal, 'alt-context'),
      announcedTotal,
    );
  }, [announcedTotal, isPending, isLoading, isAmbiguous, commitButtonLabel]);

  const commitValue = React.useCallback(
    (raw: string) => {
      if (isPending || isLoading) {
        return;
      }
      const resolution = resolveNameFaceInput(options, raw);
      if (!resolution || resolution.kind === 'ambiguous') {
        return;
      }
      onCommit(resolution);
    },
    [options, onCommit, isPending, isLoading],
  );

  const confirmDisplayedOption = React.useCallback(
    (option: ComboboxOption) => {
      if (optionSource(option) === 'person') {
        const parsed = parseNamingOptionValue(String(option.value));
        const rosterEntryId = Number.parseInt(parsed?.id ?? '', 10);
        if (Number.isFinite(rosterEntryId) && !isPending && !isLoading) {
          setChosenOptionValue(String(option.value));
          onCommit({ kind: 'roster', rosterEntryId, name: option.label.trim() });
        }
        return;
      }
      if (onOptionConfirm) {
        onOptionConfirm(option);
        return;
      }
      onValueChange(option.label);
    },
    [onOptionConfirm, onCommit, onValueChange, isPending, isLoading],
  );

  const handleSaveClick = React.useCallback(() => {
    if (overlayOpen && activeIndex >= 0 && displayedOptions[activeIndex]) {
      confirmDisplayedOption(displayedOptions[activeIndex]);
      return;
    }
    if (chosenOptionValue !== null) {
      const chosen = displayedOptions.find((o) => String(o.value) === chosenOptionValue);
      if (chosen) {
        confirmDisplayedOption(chosen);
        return;
      }
    }
    commitValue(value);
  }, [
    overlayOpen,
    activeIndex,
    displayedOptions,
    chosenOptionValue,
    value,
    confirmDisplayedOption,
    commitValue,
  ]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      if (!overlayOpen) {
        if (displayedOptions.length > 0 && !isPending && !isLoading) {
          e.preventDefault();
          setListOpen(true);
          setActiveIndex(0);
        }
        return;
      }
      e.preventDefault();
      setActiveIndex((current) => (current + 1) % displayedOptions.length);
      return;
    }
    if (e.key === 'ArrowUp') {
      if (!overlayOpen) {
        return;
      }
      e.preventDefault();
      setActiveIndex((current) =>
        current <= 0 ? displayedOptions.length - 1 : current - 1,
      );
      return;
    }
    if (e.key === 'Home') {
      if (!overlayOpen) {
        return;
      }
      e.preventDefault();
      setActiveIndex(0);
      return;
    }
    if (e.key === 'End') {
      if (!overlayOpen) {
        return;
      }
      e.preventDefault();
      setActiveIndex(displayedOptions.length - 1);
      return;
    }
    if (e.key === 'Delete') {
      if (!overlayOpen || activeIndex < 0 || !onRejectSuggestion) {
        return;
      }
      const active = displayedOptions[activeIndex];
      const suggestionId = active?.suggestion_id;
      if (typeof suggestionId === 'string' && suggestionId.length > 0) {
        e.preventDefault();
        onRejectSuggestion(suggestionId);
      }
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      if (isPending || isLoading) {
        return;
      }
      if (overlayOpen && activeIndex >= 0 && displayedOptions[activeIndex]) {
        confirmDisplayedOption(displayedOptions[activeIndex]);
        return;
      }
      commitValue(value);
      return;
    }
    if (e.key === 'Escape') {
      if (overlayOpen) {
        e.preventDefault();
        setListOpen(false);
        return;
      }
      onCancel?.();
    }
  };

  const handleConfirmOptionClick = React.useCallback(
    (option: ComboboxOption) => (event: React.MouseEvent<HTMLElement>) => {
      event.stopPropagation();
      confirmDisplayedOption(option);
    },
    [confirmDisplayedOption],
  );

  const handleRejectSuggestionClick = React.useCallback(
    (suggestionId: string) => (event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      onRejectSuggestion?.(suggestionId);
    },
    [onRejectSuggestion],
  );

  const activeOptionId =
    overlayOpen && activeIndex >= 0 ? `${listboxId}-opt-${activeIndex}` : undefined;

  const derivedSuggestionsHeader = displayedOptions.some(
    (option) => option.group === NAMING_GROUP_SUGGESTED,
  )
    ? __('Suggested', 'alt-context')
    : __('People', 'alt-context');

  return (
    <div className={className ?? classPrefix}>
      {visibleLabel && inputId ? (
        <label htmlFor={inputId} className={`${classPrefix}__visible-label`}>
          {visibleLabel}
        </label>
      ) : null}
      <div className={`${classPrefix}__input-wrapper`}>
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={overlayOpen}
          aria-haspopup="listbox"
          aria-controls={overlayOpen ? listboxId : undefined}
          aria-activedescendant={activeOptionId}
          className={`${classPrefix}__label-input`}
          id={inputId}
          value={value}
          onChange={(e) => {
            setListOpen(true);
            onValueChange(e.target.value);
          }}
          onKeyDown={handleKeyDown}
          placeholder={searchPlaceholder ?? placeholder ?? __('Enter a name…', 'alt-context')}
          disabled={isInputDisabled}
          aria-label={ariaLabel}
          aria-describedby={hint ? hintId : undefined}
        />

        {overlayOpen ? (
          <div
            className={`${classPrefix}__suggestions-overlay`}
            role="listbox"
            id={listboxId}
            aria-labelledby={`${listboxId}-label`}
          >
            <div className={`${classPrefix}__suggestions-header`} id={`${listboxId}-label`}>
              {suggestionsHeader ?? derivedSuggestionsHeader}
            </div>
            {displayedOptions.map((option, index) => {
              const optionId = `${listboxId}-opt-${index}`;
              const selected = index === activeIndex;
              const optionName = sourceBadgeLabel(option)
                ? sprintf(
                    /* translators: 1: person/group name, 2: source (Person or Group) */
                    __('%1$s (%2$s)', 'alt-context'),
                    option.label,
                    sourceBadgeLabel(option) ?? '',
                  )
                : option.label;
              return (
                <div
                  key={option.value}
                  role="presentation"
                  className={`${classPrefix}__suggestion-row${
                    selected ? ` ${classPrefix}__suggestion-row--active` : ''
                  }`}
                >
                  <div
                    id={optionId}
                    role="option"
                    aria-selected={selected}
                    className={`${classPrefix}__suggestion-item`}
                    onClick={handleConfirmOptionClick(option)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        confirmDisplayedOption(option);
                      }
                    }}
                    title={sprintf(__('Confirm match with %s', 'alt-context'), option.label)}
                    aria-label={
                      sourceBadgeLabel(option)
                        ? sprintf(
                            /* translators: 1: person/group name, 2: source (Person or Group) */
                            __('Confirm match with %1$s (%2$s)', 'alt-context'),
                            option.label,
                            sourceBadgeLabel(option) ?? '',
                          )
                        : sprintf(__('Confirm match with %s', 'alt-context'), option.label)
                    }
                  >
                    <span className={`${classPrefix}__suggestion-label`}>
                      {highlightMatch(option.label, value)}
                    </span>
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
                    <span className={`${classPrefix}__suggestion-confirm`} aria-hidden="true">
                      ✓
                    </span>
                    <span className="screen-reader-text">{optionName}</span>
                  </div>
                  {!!option.suggestion_id && !!onRejectSuggestion && (
                    <button
                      type="button"
                      tabIndex={-1}
                      className={`${classPrefix}__suggestion-reject`}
                      onClick={handleRejectSuggestionClick(option.suggestion_id as string)}
                      title={sprintf(__('Reject %s', 'alt-context'), option.label)}
                      aria-label={sprintf(__('Reject %s', 'alt-context'), option.label)}
                    >
                      ✕
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        ) : null}
        {hint}
      </div>

      {hideStatusAnnouncement ? null : (
        <p className={`${classPrefix}__result-count`} role="status" aria-live="polite">
          {resultCountAnnouncement}
        </p>
      )}

      <div className={`${classPrefix}__edit-actions`}>
        <button
          type="button"
          className={commitButtonClassName ?? `${classPrefix}__save`}
          onClick={handleSaveClick}
          disabled={isDisabled || !value.trim() || isAmbiguous}
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
