import React, { useEffect, useRef, useState } from 'react';
import { __ } from '@wordpress/i18n';

import { ConfirmTabContent } from './ConfirmTabContent';
import { useWorkbenchNav } from './WorkbenchNavContext';

const ADVANCED_DRAWER_TITLE = __('Advanced: jobs & recovery', 'alt-context');

/**
 * Disclosure region for recovery surfaces formerly hosted on the Confirm tab.
 * Focus contract: open → focus into panel; Esc → close + restore focus to trigger.
 */
export const AdvancedDrawer = (): React.JSX.Element => {
  const { isAdvancedOpen, setAdvancedOpen } = useWorkbenchNav();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const wasOpenRef = useRef(false);
  const [statusMessage, setStatusMessage] = useState('');

  useEffect(() => {
    if (isAdvancedOpen && !wasOpenRef.current) {
      setStatusMessage(__('Advanced jobs and recovery panel opened', 'alt-context'));
      const panel = panelRef.current;
      if (panel) {
        const firstFocusable = panel.querySelector<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        (firstFocusable ?? panel).focus();
      }
    } else if (!isAdvancedOpen && wasOpenRef.current) {
      setStatusMessage(__('Advanced jobs and recovery panel closed', 'alt-context'));
      triggerRef.current?.focus();
    }
    wasOpenRef.current = isAdvancedOpen;
  }, [isAdvancedOpen]);

  useEffect(() => {
    if (!isAdvancedOpen) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setAdvancedOpen(false);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [isAdvancedOpen, setAdvancedOpen]);

  return (
    <div className="acx-advanced-drawer">
      <button
        ref={triggerRef}
        type="button"
        className="acx-advanced-drawer__trigger button"
        aria-expanded={isAdvancedOpen}
        aria-controls="acx-advanced-drawer-panel"
        onClick={() => setAdvancedOpen(!isAdvancedOpen)}
      >
        {ADVANCED_DRAWER_TITLE}
      </button>
      <div className="screen-reader-text" role="status" aria-live="polite">
        {statusMessage}
      </div>
      {isAdvancedOpen ? (
        <div
          id="acx-advanced-drawer-panel"
          ref={panelRef}
          className="acx-advanced-drawer__panel"
          role="region"
          aria-label={ADVANCED_DRAWER_TITLE}
          tabIndex={-1}
        >
          <h2 className="acx-advanced-drawer__title">{ADVANCED_DRAWER_TITLE}</h2>
          <p className="acx-advanced-drawer__body">
            {__('Job history, clustering, and recovery controls for when a scan needs follow-up.', 'alt-context')}
          </p>
          <ConfirmTabContent />
        </div>
      ) : null}
    </div>
  );
};
