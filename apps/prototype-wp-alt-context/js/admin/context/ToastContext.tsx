import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react';
import * as RadixToast from '@radix-ui/react-toast';
import { __ } from '@wordpress/i18n';

type ToastType = 'success' | 'error' | 'info';

interface ToastMessage {
  id: string;
  message: string;
  type: ToastType;
}

interface ToastContextType {
  toast: (message: string, type?: ToastType) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider = ({ children }: { children: ReactNode }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, type: ToastType = 'info') => {
      const id = Math.random().toString(36).substring(2, 9);
      setToasts((prev) => [...prev, { id, message, type }]);
      setTimeout(() => removeToast(id), 5000);
    },
    [removeToast],
  );

  const success = useCallback((message: string) => toast(message, 'success'), [toast]);
  const error = useCallback((message: string) => toast(message, 'error'), [toast]);
  const info = useCallback((message: string) => toast(message, 'info'), [toast]);

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
