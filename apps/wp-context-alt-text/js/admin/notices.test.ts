import { describe, expect, it, afterEach, vi } from "vitest";

import { dispatchNotice, NOTICE_EVENT_NAME } from "./notices";

describe("dispatchNotice", () => {
    afterEach(() => {
        delete (window as any).wp;
    });

    it("delegates to the WordPress notice store when available", () => {
        const createNotice = vi.fn();
        const dispatch = vi.fn().mockReturnValue({
            createNotice,
        });

        (window as any).wp = {
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
        const infoSpy = vi.spyOn(console, "info").mockImplementation(() => {});
        const eventSpy = vi.spyOn(window, "dispatchEvent");

        dispatchNotice("info", "Hello there");

        expect(eventSpy).toHaveBeenCalledWith(
            expect.objectContaining({
                type: NOTICE_EVENT_NAME,
                detail: expect.objectContaining({
                    status: "info",
                    message: "Hello there",
                }),
            }),
        );
        expect(infoSpy).toHaveBeenCalledWith("[Context Alt Text] Hello there");

        infoSpy.mockRestore();
        eventSpy.mockRestore();
    });
});
