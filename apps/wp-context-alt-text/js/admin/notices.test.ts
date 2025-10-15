import { afterEach, describe, expect, it, vi } from "vitest";

import { dispatchNotice, NOTICE_EVENT_NAME, type NoticeStatus, type WordPressWindow } from "./notices";

interface NoticePayload {
    status: NoticeStatus;
    message: string;
    options: Record<string, unknown>;
}

const isNoticePayload = (candidate: unknown): candidate is NoticePayload => {
    if (typeof candidate !== "object" || candidate === null) {
        return false;
    }

    const { status, message, options } = candidate as {
        status?: unknown;
        message?: unknown;
        options?: unknown;
    };

    return (
        typeof status === "string" &&
        typeof message === "string" &&
        typeof options === "object" &&
        options !== null
    );
};

describe("dispatchNotice", () => {
    afterEach(() => {
        delete (window as WordPressWindow).wp;
    });

    it("delegates to the WordPress notice store when available", () => {
        const createNotice = vi.fn();
        const dispatch = vi.fn().mockReturnValue({
            createNotice,
        });

        (window as WordPressWindow).wp = {
            data: {
                dispatch,
            },
        };

        dispatchNotice("success", "Saved", { id: "notice-1" });

        expect(dispatch).toHaveBeenCalledWith("core/notices");
        expect(createNotice).toHaveBeenCalledWith(
            "success",
            "Saved",
            expect.objectContaining({
                id: "notice-1",
                type: "success",
                spokenMessage: "Saved",
            }),
        );
    });

    it("falls back to emitting a custom event when the store is unavailable", () => {
        const infoSpy = vi.spyOn(console, "info").mockImplementation(() => undefined);
        const eventSpy = vi.spyOn(window, "dispatchEvent");
        let fallbackEvent: CustomEvent<unknown> | null = null;
        const listener = (event: Event) => {
            if (event instanceof CustomEvent) {
                fallbackEvent = event;
            }
        };

        window.addEventListener(NOTICE_EVENT_NAME, listener);

        dispatchNotice("info", "Hello there");

        expect(eventSpy).toHaveBeenCalled();

        if (!fallbackEvent) {
            throw new Error("Expected fallback notice event to be dispatched");
        }

    const noticeEvent = fallbackEvent as CustomEvent<unknown>;
    const { detail } = noticeEvent;

        if (!isNoticePayload(detail)) {
            throw new Error("Fallback notice event did not include the expected payload");
        }

    expect(noticeEvent.type).toBe(NOTICE_EVENT_NAME);
        expect(detail.status).toBe("info");
        expect(detail.message).toBe("Hello there");
        expect(infoSpy).toHaveBeenCalledWith("[Context Alt Text] Hello there");

        window.removeEventListener(NOTICE_EVENT_NAME, listener);
        infoSpy.mockRestore();
        eventSpy.mockRestore();
    });
});
