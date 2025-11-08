import type { GlobalPayload } from "@/admin/types";

type BootstrapGlobal = typeof globalThis & {
    ContextAltTextAdmin?: unknown;
};

const globalRef: BootstrapGlobal = globalThis as BootstrapGlobal;

export const getAdminBootstrap = (): GlobalPayload => {
    const raw = globalRef.ContextAltTextAdmin;
    if (!raw || typeof raw !== "object") {
        return {};
    }

    return raw as GlobalPayload;
};

export const setAdminBootstrap = (payload: GlobalPayload | undefined): void => {
    if (payload === undefined) {
        delete globalRef.ContextAltTextAdmin;
        return;
    }

    globalRef.ContextAltTextAdmin = payload;
};
