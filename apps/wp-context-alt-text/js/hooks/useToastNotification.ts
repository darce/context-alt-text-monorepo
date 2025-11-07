import { useState, useCallback } from "react";

export type ToastType = "success" | "error" | "warning" | "info";

export interface ToastNotification {
    id: string;
    type: ToastType;
    message: string;
    duration?: number;
    action?: {
        label: string;
        onClick: () => void;
    };
}

/**
 * Hook for managing toast notifications with Radix UI Toast.
 *
 * This hook provides an imperative API for triggering toasts from mutation hooks
 * and other non-component code. Toasts are rendered by the consumer using the
 * returned notifications array.
 *
 * @example
 * ```tsx
 * const { notifications, addToast, removeToast } = useToastNotification();
 *
 * // In mutation onSuccess
 * addToast({
 *   type: "success",
 *   message: "Operation completed",
 *   duration: 5000
 * });
 * ```
 */
export const useToastNotification = () => {
    const [notifications, setNotifications] = useState<ToastNotification[]>([]);

    const removeToast = useCallback((id: string) => {
        setNotifications((prev) => prev.filter((toast) => toast.id !== id));
    }, []);

    const addToast = useCallback(
        (toast: Omit<ToastNotification, "id">) => {
            const id = `toast-${Date.now()}-${Math.random()}`;
            const notification: ToastNotification = {
                id,
                ...toast,
            };

            setNotifications((prev) => [...prev, notification]);

            // Auto-dismiss after duration
            if (toast.duration) {
                setTimeout(() => {
                    removeToast(id);
                }, toast.duration);
            }

            return id;
        },
        [removeToast],
    );

    return {
        notifications,
        addToast,
        removeToast,
    };
};
