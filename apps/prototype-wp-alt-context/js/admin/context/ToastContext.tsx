import React, { createContext, useContext, useState, useCallback, useEffect, useRef, ReactNode } from 'react';
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react';
import * as RadixToast from '@radix-ui/react-toast';
import { __ } from '@wordpress/i18n';

type ToastType = 'success' | 'error' | 'info';

export interface ToastAction {
  label: string;
  altText: string;
  onClick: () => void;
}

export interface ToastOptions {
  action?: ToastAction;
  /** Milliseconds before dismissal; null persists until the user dismisses it. */
  durationMs?: number | null;
}

interface ToastMessage {
  id: string;
  message: string;
  type: ToastType;
  action?: ToastAction;
  duration?: number | null;
}

interface ToastContextType {
  toast: (message: string, type?: ToastType, options?: ToastOptions) => void;
  success: (message: string, options?: ToastOptions) => void;
  error: (message: string, options?: ToastOptions) => void;
  info: (message: string, options?: ToastOptions) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider = ({ children }: { children: ReactNode }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const timerIdsRef = useRef(new Map<string, number>());

  const removeToast = useCallback((id: string) => {
    const timerId = timerIdsRef.current.get(id);
    if (timerId !== undefined) {
      window.clearTimeout(timerId);
      timerIdsRef.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(
    () => () => {
      timerIdsRef.current.forEach((timerId) => window.clearTimeout(timerId));
      timerIdsRef.current.clear();
    },
    [],
  );

  const toast = useCallback(
    (message: string, type: ToastType = 'info', options: ToastOptions = {}) => {
      const id = Math.random().toString(36).substring(2, 9);
      const duration =
        options.durationMs !== undefined ? options.durationMs : options.action ? null : 5000;
      setToasts((prev) => [...prev, { id, message, type, action: options.action, duration }]);
      if (duration !== null) {
        const timerId = window.setTimeout(() => removeToast(id), duration);
        timerIdsRef.current.set(id, timerId);
      }
    },
    [removeToast],
  );

  const success = useCallback((message: string, options?: ToastOptions) => toast(message, 'success', options), [toast]);
  const error = useCallback((message: string, options?: ToastOptions) => toast(message, 'error', options), [toast]);
  const info = useCallback((message: string, options?: ToastOptions) => toast(message, 'info', options), [toast]);

  return (
    <ToastContext.Provider value={{ toast, success, error, info }}>
      <RadixToast.Provider duration={5000} swipeDirection="right">
        {children}
        <RadixToast.Viewport className="acx-toast-container" />
        {toasts.map((t) => (
          <RadixToast.Root
            key={t.id}
            className={`acx-toast acx-toast--${t.type}`}
            open
            type={t.type === 'info' ? 'background' : 'foreground'}
            role={t.type === 'error' ? 'alert' : undefined}
            duration={t.duration ?? Infinity}
            onOpenChange={(open: boolean) => {
              if (!open) {
                removeToast(t.id);
              }
            }}
          >
            <RadixToast.Title asChild>
              <span
                className="acx-toast__icon"
                data-testid={`acx-toast-icon-${t.type}`}
                data-toast-severity={t.type}
                aria-hidden="true"
              >
                {t.type === 'success' && <CheckCircle size={18} />}
                {t.type === 'error' && <AlertCircle size={18} />}
                {t.type === 'info' && <Info size={18} />}
              </span>
            </RadixToast.Title>
            <span className="acx-toast__severity-label">
              {t.type === 'success' && __('Success', 'alt-context')}
              {t.type === 'error' && __('Error', 'alt-context')}
              {t.type === 'info' && __('Info', 'alt-context')}
            </span>
            <RadixToast.Description asChild>
              <span className="acx-toast__message">{t.message}</span>
            </RadixToast.Description>
            {t.action ? (
              <RadixToast.Action asChild altText={t.action.altText}>
                <button type="button" className="acx-toast__action" onClick={t.action.onClick}>
                  {t.action.label}
                </button>
              </RadixToast.Action>
            ) : null}
            <RadixToast.Close asChild>
              <button
                type="button"
                className="acx-toast__close"
                aria-label={__('Close', 'alt-context')}
                onClick={() => removeToast(t.id)}
              >
                <X size={14} />
              </button>
            </RadixToast.Close>
          </RadixToast.Root>
        ))}
      </RadixToast.Provider>
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};
