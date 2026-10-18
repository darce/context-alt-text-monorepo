import React, { createContext, useContext, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getConfig } from '../../api/config';
import { useTabParam } from '../../hooks/useTabParam';
import { useOverlayParam } from '../../hooks/useOverlayParam';
import { commitSearchParams } from '../../hooks/pendingSearchWrites';
import type { WorkbenchOverlay } from '../../api/recognition';
import { APP_LINK_PARAMS, APP_LINK_VALUES } from '../../navigation/appLinks';

export const TAB_IDS = {
  scan: 'scan',
} as const;

export type WorkbenchTab = (typeof TAB_IDS)[keyof typeof TAB_IDS];
export type { WorkbenchOverlay } from '../../api/recognition';

/** Re-export contract keys — appLinks is the single declaration owner (E2110-BR-06). */
export const ADVANCED_PARAM = APP_LINK_PARAMS.advanced;
export const ADVANCED_OPEN_VALUE = APP_LINK_VALUES.advancedOpen;

export interface WorkbenchNavContextValue {
  activeSection: WorkbenchTab;
  setActiveSection: (section: WorkbenchTab) => void;
  activeOverlay: WorkbenchOverlay;
  setActiveOverlay: (overlay: WorkbenchOverlay) => void;
  isAdvancedOpen: boolean;
  setAdvancedOpen: (open: boolean) => void;
  recognitionSource: 'service' | 'local';
  effectiveTargetUrl: string;
}

const WorkbenchNavContext = createContext<WorkbenchNavContextValue | null>(null);

export const WorkbenchNavProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeSection, setActiveSection] = useTabParam<WorkbenchTab>('tab', TAB_IDS.scan, [TAB_IDS.scan]);
  // Legal `panel` values: `review` | `conflicts` | `dead-letter`.
  // This overlay host owns conflicts/dead-letter (review is ignored here so
  // ClusterReviewPanel can occupy the same key). ClusterPanelContext restores
  // a previously-open overlay on review close instead of deleting `panel`.
  const [activeOverlay, setActiveOverlay] = useOverlayParam<Exclude<WorkbenchOverlay, null>>('panel', [
    'conflicts',
    'dead-letter',
  ]);
  const { recognitionSource, effectiveTargetUrl } = getConfig();

  // E21-10 Slice 4: tab=confirm shim deleted. Unknown tab values fall through to
  // useTabParam's default (scan) without rewriting the URL or opening advanced.

  const isAdvancedOpen = searchParams.get(ADVANCED_PARAM) === ADVANCED_OPEN_VALUE;

  const setAdvancedOpen = React.useCallback(
    (open: boolean): void => {
      commitSearchParams(setSearchParams, (next) => {
        if (open) {
          next.set(ADVANCED_PARAM, ADVANCED_OPEN_VALUE);
        } else {
          next.delete(ADVANCED_PARAM);
        }
      });
    },
    [setSearchParams],
  );

  const value = useMemo<WorkbenchNavContextValue>(
    () => ({
      activeSection,
      setActiveSection,
      activeOverlay,
      setActiveOverlay,
      isAdvancedOpen,
      setAdvancedOpen,
      recognitionSource,
      effectiveTargetUrl,
    }),
    [
      activeSection,
      setActiveSection,
      activeOverlay,
      setActiveOverlay,
      isAdvancedOpen,
      setAdvancedOpen,
      recognitionSource,
      effectiveTargetUrl,
    ],
  );

  return <WorkbenchNavContext.Provider value={value}>{children}</WorkbenchNavContext.Provider>;
};

export const useWorkbenchNav = (): WorkbenchNavContextValue => {
  const context = useContext(WorkbenchNavContext);
  if (!context) {
    throw new Error('useWorkbenchNav must be used within a WorkbenchNavProvider');
  }
  return context;
};
