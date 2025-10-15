type NoticeStatus = "success" | "info" | "warning" | "error";

interface NoticesDispatch {
    createNotice?: (status: NoticeStatus, content: string, options?: Record<string, unknown>) => unknown;
    removeNotice?: (id: string) => unknown;
}

const DEFAULT_NOTICE_ID = "cat-recognition-job-error";

const getNoticeDispatch = (): NoticesDispatch | null => {
    if (typeof window === "undefined") {
        return null;
    }

    const wpGlobal = (window as typeof window & {
        wp?: {
            data?: {
                dispatch?: (store: string) => unknown;
            };
        };
    }).wp;

    if (!wpGlobal?.data || typeof wpGlobal.data.dispatch !== "function") {
        return null;
    }

    try {
        const store = wpGlobal.data.dispatch("core/notices");
        if (store && typeof store === "object") {
            return store as NoticesDispatch;
        }
    } catch (error) {
         
        console.warn("Failed to access WordPress notices store", error);
    }

    return null;
};

export const pushSnackbarNotice = (status: NoticeStatus, message: string, id: string = DEFAULT_NOTICE_ID): void => {
    const normalized = typeof message === "string" ? message.trim() : "";
    if (!normalized) {
        return;
    }

    const actions = getNoticeDispatch();

    if (!actions?.createNotice) {
        return;
    }

    actions.removeNotice?.(id);
    actions.createNotice(status, normalized, {
        id,
        type: "snackbar",
        isDismissible: true,
    });
};

export const dismissNotice = (id: string = DEFAULT_NOTICE_ID): void => {
    const actions = getNoticeDispatch();
    actions?.removeNotice?.(id);
};

declare global {
    interface Window {
        wp?: {
            data?: {
                dispatch?: (store: string) => unknown;
            };
        };
    }
}
