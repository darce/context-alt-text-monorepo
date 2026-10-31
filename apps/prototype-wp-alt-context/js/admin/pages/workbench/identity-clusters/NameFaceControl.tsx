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

import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';

import type { ComboboxMatchBand, ComboboxOption } from '../../../../components/ui/combobox';
import { NAMING_GROUP_SUGGESTED, parseNamingOptionValue } from './buildNamingOptions';
import { ACCENT_PRIMARY_ATTR } from '../mediaFooterCtaState';

export type NameFaceResolution =
  | { readonly kind: 'roster'; readonly rosterEntryId: number; readonly name: string }
  | { readonly kind: 'create'; readonly name: string }
  | { readonly kind: 'ambiguous'; readonly name: string; readonly matches: readonly ComboboxOption[] };

/** Similarity at-or-above this threshold uses the high match-score band. */
const MATCH_BAND_HIGH_THRESHOLD = 0.7;

const LIVE_ANNOUNCE_DEBOUNCE_MS = 400;

/** Read before React replaces the initiating button with the inline editor. */
const captureNamingOpener = () => {
  const element = document.activeElement;
  if (!(element instanceof HTMLElement) || element === document.body) {
    return null;
  }
  const parent = element.parentElement;
  const tag = element.tagName;
  const text = element.textContent;
  const label = element.getAttribute('aria-label');
  const id = element.id;
  return () => {
    if (element.isConnected) {
      element.focus();
      return;
    }
    // Library recreates its label and action buttons on cancel. Stay inside
    // their original parent; never find an identically named person elsewhere.
    if (parent?.isConnected) {
      const replacement = Array.from(parent.children).find((child) =>
        child instanceof HTMLElement && child.tagName === tag && child.id === id
        && child.textContent === text && child.getAttribute('aria-label') === label,
      );
      if (replacement instanceof HTMLElement) {
        replacement.focus();
      }
    }
  };
};

/** Native scrolling accounts for every scrollport and its scroll padding. */
const revealNamingEditor = (editor: HTMLElement, input: HTMLInputElement) => {
  const options: ScrollIntoViewOptions = { block: 'nearest', inline: 'nearest', behavior: 'instant' };
  editor.scrollIntoView(options);
  // The Library's row scrollport can be shorter than the complete form. Keep
  // the focused field visible even when all the actions cannot fit beside it.
  input.scrollIntoView(options);
};

export const normalizeNameFaceLabel = (raw: string): string =>
  raw.normalize('NFC').replace(/\s+/g, ' ').trim().toLocaleLowerCase();

const optionSource = (option: ComboboxOption): 'person' | 'cluster' | null => {
  const source =
    option.source === 'person' || option.source === 'cluster'
      ? option.source
      : parseNamingOptionValue(String(option.value))?.source;
  return source ?? null;
};

/** Band display for backend roster-candidate rows: a band word, never a bare percentage (HAI-08). */
const matchBandDisplay = (band: ComboboxMatchBand): { label: string; tone: 'high' | 'medium' | 'weak' } => {
  if (band === 'strong') {
    return { label: __('Strong match', 'alt-context'), tone: 'high' };
  }
  if (band === 'possible') {
    return { label: __('Possible match', 'alt-context'), tone: 'medium' };
  }
  return { label: __('Below match threshold', 'alt-context'), tone: 'weak' };
};

const personMatchesFor = (
  options: readonly ComboboxOption[],
  raw: string,
): ComboboxOption[] => {
  const folded = normalizeNameFaceLabel(raw);
  if (!folded) {
    return [];
  }
  const seen = new Set<string>();
  return options.filter((option) => {
    if (optionSource(option) !== 'person' || normalizeNameFaceLabel(option.label) !== folded) {
      return false;
    }
    const key = String(option.value);
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
};

/** Producers resolve binding proof before truncation; the control dedupes IDs only. */
const canonicalNamingOptions = (
  options: readonly ComboboxOption[],
): ComboboxOption[] => {
  const seen = new Set<string>();
  const canonical: ComboboxOption[] = [];
  for (const option of options) {
    const key = String(option.value);
    if (!seen.has(key)) {
      seen.add(key);
      canonical.push(option);
    }
  }
  return canonical;
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
  return options.filter((option) =>
    (optionSource(option) === 'person' && option.roster_entry_id != null && option.band !== undefined)
    || normalizeNameFaceLabel(option.label).includes(folded),
  );
};

interface NameFaceControlProps {
  /** Naming options (roster persons ∪ labelled groups ∪ similarity suggestions). */
  options: readonly ComboboxOption[];
  /**
   * Create-vs-bind candidate set. Defaults to `options`. Pass the unfiltered,
   * untruncated union so resolution does not inherit the displayed slice.
   */
  resolutionOptions?: readonly ComboboxOption[];
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
  /** Roster/options still loading — announced, commit blocked. */
  isLoading?: boolean;
  /** Override for draft editing (defaults to isPending || isLoading). */
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
  /** The suggestion read failed: shown as an explicit error, never as an empty list. */
  suggestionsError?: boolean;
  /** Re-runs the failed suggestion read; the retry control renders only when provided. */
  onRetrySuggestions?: () => void;
}

export const NameFaceControl = ({
  options,
  resolutionOptions = options,
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
  suggestionsError = false,
  onRetrySuggestions,
}: NameFaceControlProps): React.JSX.Element => {
  const editorRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [restoreOpener] = useState(() => captureNamingOpener());
  const focusedOnOpen = useRef(false);
  const reactId = useId();
  const listboxId = `acx-name-face-listbox-${reactId}`;
  const [activeIndex, setActiveIndex] = useState(-1);
  const [announcedTotal, setAnnouncedTotal] = useState<number | null>(null);
  const [chosenOptionValue, setChosenOptionValue] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const isDisabled = isPending || disabled || isLoading;
  // Library explicitly permits drafting during unavailable reads. The override
  // controls loading as well as pending; commit gates remain independent.
  const isInputDisabled = disabled || (inputDisabled ?? (isPending || isLoading));

  useLayoutEffect(() => {
    const input = inputRef.current;
    const editor = editorRef.current;
    if (!autoFocus || isInputDisabled || !input || !editor) {
      return;
    }
    if (!focusedOnOpen.current) {
      focusedOnOpen.current = true;
      input.focus({ preventScroll: true });
      input.select();
    }
    const reveal = () => {
      if (editor.isConnected && document.activeElement === input) {
        revealNamingEditor(editor, input);
      }
    };
    reveal();
    // Table-cell wrapping, async hints/status, images and fonts can move the
    // editor after the opening effect; pane resizing changes its clip as well.
    // Observe this editor's ancestor chain, not the document or a polling loop.
    // ResizeObserver delivers after layout, including an initial delivery.
    const observer = new ResizeObserver(reveal);
    for (let node: HTMLElement | null = editor;
      node && node !== document.body && node !== document.documentElement;
      node = node.parentElement) {
      observer.observe(node, { box: 'border-box' });
    }
    return () => observer.disconnect();
  }, [autoFocus, isInputDisabled]);

  const handleCancel = () => {
    const editor = editorRef.current;
    onCancel?.();
    // The caller owns draft retention and replaces the editor after this event.
    // Do not return focus on unrelated unmounts or steal a later focus choice.
    queueMicrotask(() => {
      if (editor && !editor.isConnected && document.activeElement === document.body) {
        restoreOpener?.();
      }
    });
  };

  const canonicalOptions = React.useMemo(
    () => canonicalNamingOptions(options),
    [options],
  );
  const matchingOptions = React.useMemo(
    () => matchingOptionsFor(canonicalOptions, value),
    [canonicalOptions, value],
  );
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
    () => resolveNameFaceInput(resolutionOptions, value),
    [resolutionOptions, value],
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
        ? resolveNameFaceInput(resolutionOptions, activeOption.label)
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
    resolutionOptions,
  ]);

  const ambiguousMatches = React.useMemo(
    () => (value.trim() ? personMatchesFor(resolutionOptions, value) : []),
    [resolutionOptions, value],
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
      const resolution = resolveNameFaceInput(resolutionOptions, raw);
      if (!resolution || resolution.kind === 'ambiguous') {
        return;
      }
      onCommit(resolution);
    },
    [resolutionOptions, onCommit, isPending, isLoading],
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
      if (onCancel) {
        e.preventDefault();
        e.stopPropagation();
        handleCancel();
      }
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

  // "No close match" never commits an empty name: with a typed name it creates that name,
  // otherwise it moves focus to manual entry.
  const handleAbstainClick = React.useCallback(() => {
    if (commitResolution?.kind === 'create' && !isPending && !isLoading) {
      onCommit(commitResolution);
      return;
    }
    inputRef.current?.focus();
  }, [commitResolution, isPending, isLoading, onCommit]);

  const activeOptionId =
    overlayOpen && activeIndex >= 0 ? `${listboxId}-opt-${activeIndex}` : undefined;

  const derivedSuggestionsHeader = displayedOptions.some(
    (option) => option.group === NAMING_GROUP_SUGGESTED,
  )
    ? __('Suggested', 'alt-context')
    : __('People', 'alt-context');

  return (
    <div ref={editorRef} className={className ?? classPrefix}>
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
          aria-label={visibleLabel && inputId ? undefined : ariaLabel}
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
              const bandDisplay = option.band === undefined ? null : matchBandDisplay(option.band);
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
                    aria-label={sprintf(__('Confirm match with %s', 'alt-context'), option.label)}
                  >
                    <span className={`${classPrefix}__suggestion-label`}>
                      {highlightMatch(option.label, value)}
                    </span>
                    {bandDisplay !== null && (
                      <span className={`${classPrefix}__match-score ${classPrefix}__match-score--${bandDisplay.tone}`}>
                        <span className={`${classPrefix}__match-score-band`}>{bandDisplay.label}</span>
                      </span>
                    )}
                    {bandDisplay === null && option.similarity !== undefined && (
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
                    <span className="screen-reader-text">{option.label}</span>
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
        {overlayOpen && displayedOptions.some((option) => option.band !== undefined) ? (
          <button type="button" className={`${classPrefix}__abstain`} onClick={handleAbstainClick}>
            {__('No close match: name as new person', 'alt-context')}
          </button>
        ) : null}
        {hint}
      </div>

      {hideStatusAnnouncement ? null : (
        <p className={`${classPrefix}__result-count`} role="status" aria-live="polite">
          {resultCountAnnouncement}
        </p>
      )}

      {suggestionsError ? (
        <div className={`${classPrefix}__suggestions-error`} role="alert">
          <span>{__('Could not load name suggestions.', 'alt-context')}</span>
          {onRetrySuggestions ? (
            <button
              type="button"
              className={`${classPrefix}__suggestions-retry`}
              onClick={onRetrySuggestions}
              disabled={isPending || isLoading || disabled}
            >
              {__('Retry', 'alt-context')}
            </button>
          ) : null}
        </div>
      ) : null}

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
          <button type="button" className={`${classPrefix}__cancel`} onClick={handleCancel}>
            {__('Cancel', 'alt-context')}
          </button>
        ) : null}
      </div>
    </div>
  );
};
