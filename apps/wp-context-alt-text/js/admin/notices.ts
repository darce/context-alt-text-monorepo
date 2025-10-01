export type NoticeStatus = "success" | "info" | "warning" | "error";

export interface NoticeAction {
    label: string;
    url?: string;
    onClick?: () => void;
    className?: string;
}

export interface NoticeOptions {
    id?: string;
    spokenMessage?: string;
    isDismissible?: boolean;
    actions?: NoticeAction[];
}

const WP_NOTICE_STORE = "core/notices";
const FALLBACK_EVENT_NAME = "cat:workbench:notice";

const getWpNoticeDispatcher = () => {
    if (typeof window === "undefined") {
        return null;
    }

    const wp = (window as any)?.wp;
    if (!wp || !wp.data || typeof wp.data.dispatch !== "function") {
        return null;
    }

    try {
        const dispatcher = wp.data.dispatch(WP_NOTICE_STORE);
        if (dispatcher && typeof dispatcher.createNotice === "function") {
            return dispatcher as {
                createNotice: (type: NoticeStatus, message: string, options?: Record<string, unknown>) => void;
            };
        }
    } catch (error) {
        console.warn("[Context Alt Text] Failed to access WordPress notice store", error);
    }

    return null;
};

const emitFallbackNotice = (status: NoticeStatus, message: string, options?: NoticeOptions) => {
    if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
        window.dispatchEvent(
            new CustomEvent(FALLBACK_EVENT_NAME, {
                detail: {
                    status,
                    message,
                    options: options ?? {},
                },
            }),
        );
    }
};

export const dispatchNotice = (status: NoticeStatus, message: string, options?: NoticeOptions) => {
    const dispatcher = getWpNoticeDispatcher();

    if (dispatcher) {
        dispatcher.createNotice(status, message, {
            type: status,
            id: options?.id,
            isDismissible: options?.isDismissible ?? true,
            spokenMessage: options?.spokenMessage ?? message,
            actions: options?.actions,
        });
        return;
    }

    emitFallbackNotice(status, message, options);

    const logger = status === "error" ? console.error : console.info;
    logger.call(console, `[Context Alt Text] ${message}`);
};

export const notifySuccess = (message: string, options?: NoticeOptions) => dispatchNotice("success", message, options);
export const notifyInfo = (message: string, options?: NoticeOptions) => dispatchNotice("info", message, options);
export const notifyWarning = (message: string, options?: NoticeOptions) => dispatchNotice("warning", message, options);
export const notifyError = (message: string, options?: NoticeOptions) => dispatchNotice("error", message, options);

export const NOTICE_EVENT_NAME = FALLBACK_EVENT_NAME;
