import * as React from "react";
import { useToastNotification, ToastType } from "@/hooks/useToastNotification";
import {
    ToastProvider as RadixToastProvider,
    ToastViewport,
    Toast,
    ToastTitle,
    ToastClose,
    ToastAction,
} from "@/components/ui/toast";
import { __ } from "@wordpress/i18n";

interface ToastContextValue {
    addToast: (toast: {
        type: ToastType;
        message: string;
        duration?: number;
        action?: {
            label: string;
            onClick: () => void;
        };
    }) => string;
    removeToast: (id: string) => void;
}

const ToastContext = React.createContext<ToastContextValue | undefined>(undefined);

/**
 * Toast Provider that wraps Radix UI Toast with an imperative API.
 * This allows mutation hooks to trigger toasts without needing to render components directly.
 */
export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const { notifications, addToast, removeToast } = useToastNotification();

    return (
        <ToastContext.Provider value={{ addToast, removeToast }}>
            <RadixToastProvider swipeDirection="right">
                {children}
                {notifications.map((notification) => (
                    <Toast
                        key={notification.id}
                        duration={notification.duration ?? 5000}
                        onOpenChange={(open) => {
                            if (!open) {
                                removeToast(notification.id);
                            }
                        }}
                        className={`cat-toast--${notification.type}`}
                    >
                        <ToastTitle>{notification.message}</ToastTitle>
                        {notification.action && (
                            <ToastAction altText={notification.action.label} onClick={notification.action.onClick}>
                                {notification.action.label}
                            </ToastAction>
                        )}
                        <ToastClose aria-label={__("Close", "context-alt-text")} />
                    </Toast>
                ))}
                <ToastViewport />
            </RadixToastProvider>
        </ToastContext.Provider>
    );
};

/**
 * Hook to access toast notification API from any component or mutation hook.
 * Must be used within ToastProvider.
 */
export const useToast = () => {
    const context = React.useContext(ToastContext);
    if (!context) {
        throw new Error("useToast must be used within ToastProvider");
    }
    return context;
};
