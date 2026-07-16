import React, { createContext, useContext, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getConfig } from '../../api/config';
import { useTabParam } from '../../hooks/useTabParam';
import { useOverlayParam } from '../../hooks/useOverlayParam';
import type { WorkbenchOverlay } from '../../api/recognition';

export const TAB_IDS = {
  scan: 'scan',
} as const;

/** Legacy deep-link value only — URL shim maps it to scan + advanced open. */
export const LEGACY_CONFIRM_TAB = 'confirm';

export type WorkbenchTab = (typeof TAB_IDS)[keyof typeof TAB_IDS];
export type { WorkbenchOverlay } from '../../api/recognition';

export const ADVANCED_PARAM = 'advanced';
export const ADVANCED_OPEN_VALUE = 'open';

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
  const [activeOverlay, setActiveOverlay] = useOverlayParam<Exclude<WorkbenchOverlay, null>>('panel', [
    'conflicts',
    'dead-letter',
  ]);
  const { recognitionSource, effectiveTargetUrl } = getConfig();

  // shim owned by E21-10 — maps legacy ?tab=confirm to scan + advanced drawer open
  useEffect(() => {
    if (searchParams.get('tab') !== LEGACY_CONFIRM_TAB) {
      return;
    }
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set('tab', TAB_IDS.scan);
        next.set(ADVANCED_PARAM, ADVANCED_OPEN_VALUE);
        return next;
      },
      { replace: true },
    );
  }, [searchParams, setSearchParams]);

  const isAdvancedOpen = searchParams.get(ADVANCED_PARAM) === ADVANCED_OPEN_VALUE;

  const setAdvancedOpen = React.useCallback(
    (open: boolean): void => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (open) {
            next.set(ADVANCED_PARAM, ADVANCED_OPEN_VALUE);
          } else {
            next.delete(ADVANCED_PARAM);
          }
          return next;
        },
        { replace: true },
      );
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
