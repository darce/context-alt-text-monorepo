import {
  Fragment,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type JSX,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type RefObject,
} from 'react';
import { __ } from '@wordpress/i18n';

import { APP_LINK_VALUES, type PanesState } from '../../navigation/appLinks';

/** Collapse/host state owned by the caller (URL codec lives in appLinks). [sr-007] */
export type WorkbenchPanesState = PanesState;

/** Default stack breakpoint: ~320px / 200% zoom [A11Y-08]. */
export const DEFAULT_STACK_BELOW_PX = 320;

/** Control share of the split (library gets the remainder — dominant [LAY-01]). */
export const DEFAULT_SPLIT_RATIO = 35;
export const SPLIT_RATIO_MIN = 15;
export const SPLIT_RATIO_MAX = 70;
export const SPLIT_RATIO_STEP = 5;

/** Pointer clientX delta → percentage of control width (geometry-free; jsdom-safe). */
const POINTER_RATIO_PER_PX = 0.25;

export interface WorkbenchTwoPaneLayoutProps {
  /** LEFT host content slot. */
  control: ReactNode;
  /** RIGHT host content slot (dominant region [LAY-01]). */
  library: ReactNode;
  /** Current collapse state from the caller. */
  panes: WorkbenchPanesState;
  /** Collapse writes go here; caller owns persistence (e.g. `?panes=`). */
  onPanesChange: (next: WorkbenchPanesState) => void;
  /** Width at/below which panes stack vertically (library first). */
  stackBelowPx?: number;
}

/** Narrow ReactNode's Iterable member to a real array so children are ReactNode, not any. */
const isReactNodeArray = (node: ReactNode): node is readonly ReactNode[] => Array.isArray(node);

const isSlotEmpty = (node: ReactNode): boolean => {
  if (node == null || node === false || node === true) {
    return true;
  }
  if (typeof node === 'string') {
    return node.trim() === '';
  }
  if (typeof node === 'number') {
    return false;
  }
  if (isReactNodeArray(node)) {
    return node.every((child) => isSlotEmpty(child));
  }
  if (isValidElement(node) && node.type === Fragment) {
    return isSlotEmpty((node.props as { children?: ReactNode }).children);
  }
  return false;
};

const clampRatio = (value: number): number => Math.min(SPLIT_RATIO_MAX, Math.max(SPLIT_RATIO_MIN, value));

const useStackMatch = (stackBelowPx: number): boolean => {
  const query = `(max-width: ${stackBelowPx}px)`;

  const [stacked, setStacked] = useState(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return false;
    }
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return undefined;
    }

    const mql = window.matchMedia(query);
    const onChange = (event: MediaQueryListEvent): void => {
      setStacked(event.matches);
    };

    setStacked(mql.matches);

    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    }

    mql.addListener(onChange);
    return () => mql.removeListener(onChange);
  }, [query]);

  return stacked;
};

const nextCollapseState = (current: WorkbenchPanesState): WorkbenchPanesState => {
  if (current === APP_LINK_VALUES.panesBoth) {
    return APP_LINK_VALUES.panesControlCollapsed;
  }
  if (current === APP_LINK_VALUES.panesControlCollapsed) {
    return APP_LINK_VALUES.panesLibraryCollapsed;
  }
  return APP_LINK_VALUES.panesBoth;
};

interface PaneHostProps {
  kind: 'control' | 'library';
  collapsed: boolean;
  children: ReactNode;
  labelledBy: string;
  title: string;
  zeroStateMessage: string;
  style?: CSSProperties;
  hostRef?: RefObject<HTMLElement>;
}

const PaneHost = ({
  kind,
  collapsed,
  children,
  labelledBy,
  title,
  zeroStateMessage,
  style,
  hostRef,
}: PaneHostProps): JSX.Element => {
  const empty = isSlotEmpty(children);
  const dominant = kind === 'library';

  return (
    <section
      ref={hostRef as RefObject<HTMLElement>}
      className={`acx-workbench__two-pane-${kind}`}
      data-testid={`workbench-two-pane-${kind}`}
      data-dominant={dominant ? 'true' : 'false'}
      data-collapsed={collapsed ? 'true' : 'false'}
      data-empty={empty ? 'true' : 'false'}
      aria-labelledby={labelledBy}
      hidden={collapsed || undefined}
      style={style}
    >
      <h2 id={labelledBy} className="acx-workbench__two-pane-title">
        {title}
      </h2>
      {empty ? (
        <div className="acx-workbench__two-pane-zero" role="status">
          <p className="acx-workbench__two-pane-zero-message">{zeroStateMessage}</p>
        </div>
      ) : (
        <div className="acx-workbench__two-pane-slot">{children}</div>
      )}
    </section>
  );
};

interface SplitterProps {
  stacked: boolean;
  ratio: number;
  panes: WorkbenchPanesState;
  onRatioChange: (next: number) => void;
  onPanesChange: (next: WorkbenchPanesState) => void;
  splitterRef?: RefObject<HTMLDivElement>;
}

const TwoPaneSplitter = ({
  stacked,
  ratio,
  panes,
  onRatioChange,
  onPanesChange,
  splitterRef,
}: SplitterProps): JSX.Element => {
  // Refs so pointer-move in the same event turn (jsdom fireEvent) sees drag start
  // without waiting for React state, and without getBoundingClientRect geometry.
  const draggingRef = useRef(false);
  const lastClientXRef = useRef(0);
  const [dragging, setDragging] = useState(false);
  const ratioRef = useRef(ratio);
  ratioRef.current = ratio;

  const sideBySideLabel = __('Resize control and library panels', 'alt-context');
  const sectionToggleLabel = __('Toggle control and library sections', 'alt-context');
  const label = stacked ? sectionToggleLabel : sideBySideLabel;

  const adjustRatio = useCallback(
    (delta: number) => {
      onRatioChange(clampRatio(ratioRef.current + delta));
    },
    [onRatioChange],
  );

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (stacked) {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onPanesChange(nextCollapseState(panes));
      }
      return;
    }

    switch (event.key) {
      case 'ArrowLeft':
        event.preventDefault();
        adjustRatio(-SPLIT_RATIO_STEP);
        break;
      case 'ArrowRight':
        event.preventDefault();
        adjustRatio(SPLIT_RATIO_STEP);
        break;
      case 'ArrowUp':
        event.preventDefault();
        adjustRatio(-SPLIT_RATIO_STEP);
        break;
      case 'ArrowDown':
        event.preventDefault();
        adjustRatio(SPLIT_RATIO_STEP);
        break;
      case 'Home':
        event.preventDefault();
        onRatioChange(SPLIT_RATIO_MIN);
        break;
      case 'End':
        event.preventDefault();
        onRatioChange(SPLIT_RATIO_MAX);
        break;
      case 'Enter':
        event.preventDefault();
        onPanesChange(nextCollapseState(panes));
        break;
      default:
        break;
    }
  };

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (stacked) {
      return;
    }
    event.preventDefault();
    draggingRef.current = true;
    lastClientXRef.current = event.clientX;
    setDragging(true);
    const target = event.currentTarget;
    if (typeof target.setPointerCapture === 'function') {
      target.setPointerCapture(event.pointerId);
    }
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (!draggingRef.current || stacked) {
      return;
    }
    // Drive off clientX deltas (jsdom fireEvent sets clientX; no layout geometry).
    const deltaX = event.clientX - lastClientXRef.current;
    if (deltaX === 0) {
      return;
    }
    lastClientXRef.current = event.clientX;
    onRatioChange(clampRatio(ratioRef.current + deltaX * POINTER_RATIO_PER_PX));
  };

  const endDrag = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (!draggingRef.current) {
      return;
    }
    draggingRef.current = false;
    setDragging(false);
    const target = event.currentTarget;
    if (typeof target.releasePointerCapture === 'function') {
      try {
        target.releasePointerCapture(event.pointerId);
      } catch {
        // Already released or unsupported.
      }
    }
  };

  const handleClick = (): void => {
    if (stacked) {
      onPanesChange(nextCollapseState(panes));
    }
  };

  return (
    <div
      ref={splitterRef}
      role="separator"
      tabIndex={0}
      className="acx-workbench__two-pane-splitter"
      data-mode={stacked ? 'section-toggle' : 'resize'}
      data-dragging={dragging ? 'true' : 'false'}
      aria-orientation={stacked ? 'horizontal' : 'vertical'}
      aria-valuenow={stacked ? undefined : Math.round(ratio)}
      aria-valuemin={stacked ? undefined : SPLIT_RATIO_MIN}
      aria-valuemax={stacked ? undefined : SPLIT_RATIO_MAX}
      aria-label={label}
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onClick={handleClick}
    />
  );
};

/**
 * Presentational two-pane workbench host: control (left) + library (right, dominant)
 * separated by a keyboard/pointer splitter. Collapse state is controlled via props;
 * URL / `usePanesParam` wiring belongs to a later slice.
 */
export const WorkbenchTwoPaneLayout = ({
  control,
  library,
  panes,
  onPanesChange,
  stackBelowPx = DEFAULT_STACK_BELOW_PX,
}: WorkbenchTwoPaneLayoutProps): JSX.Element => {
  const stacked = useStackMatch(stackBelowPx);
  const [splitRatio, setSplitRatio] = useState(DEFAULT_SPLIT_RATIO);
  const controlTitleId = useId();
  const libraryTitleId = useId();
  const controlHostRef = useRef<HTMLElement>(null);
  const libraryHostRef = useRef<HTMLElement>(null);
  const splitterRef = useRef<HTMLDivElement>(null);

  const controlCollapsed = panes === APP_LINK_VALUES.panesControlCollapsed;
  const libraryCollapsed = panes === APP_LINK_VALUES.panesLibraryCollapsed;

  // L2V-02: if focus is inside a pane that just collapsed, move it to the splitter
  // so keyboard users are not trapped on a hidden node.
  useEffect(() => {
    const active = document.activeElement;
    if (!(active instanceof Node)) {
      return;
    }
    const trappedInControl = controlCollapsed && controlHostRef.current?.contains(active);
    const trappedInLibrary = libraryCollapsed && libraryHostRef.current?.contains(active);
    if ((trappedInControl || trappedInLibrary) && splitterRef.current) {
      splitterRef.current.focus();
    }
  }, [controlCollapsed, libraryCollapsed]);

  const controlTitle = __('Control', 'alt-context');
  const libraryTitle = __('Library', 'alt-context');
  const controlZero = __(
    'Recognition and cluster controls will appear here. Run recognition when media is ready.',
    'alt-context',
  );
  const libraryZero = __(
    'Media library will appear here. Select or filter media to caption and describe.',
    'alt-context',
  );

  const controlStyle: CSSProperties | undefined =
    !stacked && panes === APP_LINK_VALUES.panesBoth
      ? {
          flexGrow: 0,
          flexShrink: 0,
          flexBasis: `${splitRatio}%`,
        }
      : undefined;

  const libraryStyle: CSSProperties | undefined =
    !stacked && panes === APP_LINK_VALUES.panesBoth
      ? {
          flexGrow: 1,
          flexShrink: 1,
          flexBasis: `${100 - splitRatio}%`,
        }
      : undefined;

  const controlHost = (
    <PaneHost
      kind="control"
      collapsed={controlCollapsed}
      labelledBy={controlTitleId}
      title={controlTitle}
      zeroStateMessage={controlZero}
      style={controlStyle}
      hostRef={controlHostRef}
    >
      {control}
    </PaneHost>
  );

  const libraryHost = (
    <PaneHost
      kind="library"
      collapsed={libraryCollapsed}
      labelledBy={libraryTitleId}
      title={libraryTitle}
      zeroStateMessage={libraryZero}
      style={libraryStyle}
      hostRef={libraryHostRef}
    >
      {library}
    </PaneHost>
  );

  const splitter = (
    <TwoPaneSplitter
      stacked={stacked}
      ratio={splitRatio}
      panes={panes}
      onRatioChange={setSplitRatio}
      onPanesChange={onPanesChange}
      splitterRef={splitterRef}
    />
  );

  // Stacked: library first (dominant) [LAY-01]/[A11Y-08]. Side-by-side: control | splitter | library.
  return (
    <div
      className="acx-workbench__two-pane"
      data-testid="workbench-two-pane"
      data-layout={stacked ? 'stacked' : 'side-by-side'}
      data-panes={panes}
    >
      {stacked ? (
        <>
          {libraryHost}
          {splitter}
          {controlHost}
        </>
      ) : (
        <>
          {controlHost}
          {splitter}
          {libraryHost}
        </>
      )}
    </div>
  );
};
