import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { axe } from "vitest-axe";
import { http, HttpResponse } from "msw";

const { dispatchNoticeMock, notifyErrorMock } = vi.hoisted(() => ({
    dispatchNoticeMock: vi.fn(),
    notifyErrorMock: vi.fn(),
}));

vi.mock("@/admin/notices", () => ({
    dispatchNotice: dispatchNoticeMock,
    notifyError: notifyErrorMock,
    NOTICE_EVENT_NAME: "cat:workbench:notice",
}));

import { App } from "./App";
import { useDashboardHandlers } from "@/admin/testing/mswServer";

const COVERAGE_ENDPOINT = "https://example.com/wp-json/cat/v1/dashboard/coverage";

const bootstrapPayload = {
    hero: {
        state: "ready" as const,
        message: "We found 12 images missing alt text.",
        cta_label: "Open Alt-Text Workbench",
        cta_url: "/wp-admin/admin.php?page=context-alt-text-workbench",
        last_updated_human: "5 minutes",
    },
    coverage: {
        total: 40,
        with_alt: 28,
        missing: 12,
        coverage_percent: 70,
        trend_series: [],
    },
    latestActivity: {
        last_recognition: null,
        last_alt_text_generation: null,
        last_roster_sync: null,
    },
    recognition: {
        pending_faces: 0,
        pending_brands: 0,
        unresolved_matches: 0,
    },
    automation: {
        queued: 0,
        running: 0,
        completed: 0,
        next_run: null,
    },
    footer: {
        actions: [
            { label: "Run scan again", url: "/wp-admin/admin.php?page=context-alt-text-scan" },
            { label: "Open Alt-Text Workbench", url: "/wp-admin/admin.php?page=context-alt-text-workbench" },
        ],
        statusText: "Last scan completed 5 minutes ago.",
    },
};

const workbenchBootstrapData = {
    viewMode: "list" as const,
    pagination: {
        page: 1,
        perPage: 20,
        total: 1,
        totalPages: 1,
    },
    items: [
        {
            id: "123",
            title: "Sample image",
            status: "missing" as const,
            updatedAt: "2024-01-01T00:00:00.000Z",
            altText: "",
            mimeType: "image/jpeg",
            dimensions: { width: 1920, height: 1080 },
            editUrl: "https://example.com/wp-admin/post.php?post=123&action=edit",
        },
    ],
};

describe("App", () => {
    beforeEach(() => {
        dispatchNoticeMock.mockReset();
        notifyErrorMock.mockReset();

        (globalThis as any).ContextAltTextAdmin = {
            config: {
                endpoints: {
                    coverage: COVERAGE_ENDPOINT,
                },
                restNonce: "dashboard-nonce",
            },
            data: {
                dashboard: bootstrapPayload,
            },
        };

        useDashboardHandlers(
            http.get(COVERAGE_ENDPOINT, () => {
                console.info("coverage handler invoked");
                return HttpResponse.json({
                    total: 44,
                    with_alt: 40,
                    missing: 4,
                    coverage_percent: 90,
                    trend_series: [
                        {
                            timestamp: Date.now() - 60_000,
                            coverage: 80,
                            total: 40,
                            with_alt: 32,
                            missing: 8,
                        },
                        {
                            timestamp: Date.now(),
                            coverage: 90,
                            total: 44,
                            with_alt: 40,
                            missing: 4,
                        },
                    ],
                });
            }),
        );
    });

    afterEach(() => {
        (globalThis as any).ContextAltTextAdmin = undefined;
    });

    it("hydrates the dashboard and passes accessibility checks", async () => {
        const { container } = render(<App />);

        expect(screen.getByText(/We found 12 images missing alt text/i)).toBeInTheDocument();

        await screen.findByRole("img", { name: /Coverage 70%/i });

        const results = await axe(container);
        expect(results).toHaveNoViolations();
    });

    it("renders the workbench when requested", () => {
        (globalThis as any).ContextAltTextAdmin = {
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                    workbenchRecognition: true,
                    workbenchBulkAI: true,
                },
                endpoints: {
                    workbenchMedia: "https://example.com/wp-json/context-alt-text/v1/workbench/media",
                },
            },
            data: {
                workbench: workbenchBootstrapData,
            },
        };

        const { getByText } = render(<App />);

        expect(getByText(/Sample image/i)).toBeInTheDocument();
        expect(getByText(/image\/jpeg/i)).toBeInTheDocument();
        expect(screen.getByRole("table", { name: /Media queue/i })).toBeInTheDocument();
    });

    it("emits workbench seen analytics once when route loads", () => {
        (globalThis as any).ContextAltTextAdmin = {
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                },
            },
            data: {
                workbench: workbenchBootstrapData,
            },
        };

        const dispatchEventSpy = vi.spyOn(window, "dispatchEvent");
        render(<App />);

        const seenEvents = dispatchEventSpy.mock.calls.filter(([event]) => event.type === "cat_workbench_seen");
        expect(seenEvents).toHaveLength(1);
        const [seenEvent] = seenEvents[0];
        expect(seenEvent.detail).toMatchObject({
            pagination: {
                page: 1,
                perPage: 20,
            },
            viewMode: "list",
            filters: {
                status: "missing",
                search: null,
            },
        });

        dispatchEventSpy.mockRestore();
    });

    it("dispatches notices when bulk actions are triggered", () => {
        (globalThis as any).ContextAltTextAdmin = {
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                    workbenchRecognition: true,
                    workbenchBulkAI: true,
                },
            },
            data: {
                workbench: workbenchBootstrapData,
            },
        };

        const dispatchEventSpy = vi.spyOn(window, "dispatchEvent");
        render(<App />);

        const checkbox = screen.getByRole("checkbox", { name: /Select Sample image/i });
        fireEvent.click(checkbox);

        const generateButton = screen.getByRole("button", { name: /Generate Alt Text/i });
        fireEvent.click(generateButton);

        expect(dispatchNoticeMock).toHaveBeenCalledWith(
            "info",
            "Preparing to generate alt text for 1 item.",
            expect.objectContaining({
                id: "workbench-bulk-generate",
                spokenMessage: "Preparing to generate alt text for 1 item.",
            }),
        );
        expect(dispatchNoticeMock).toHaveBeenCalledTimes(1);

        const bulkEvents = dispatchEventSpy.mock.calls.filter(([event]) => event.type === "cat_workbench_bulk_action");
        expect(bulkEvents).toHaveLength(1);
        const [bulkEvent] = bulkEvents[0];
        expect(bulkEvent.detail).toMatchObject({
            action: "generate",
            count: 1,
            selection: ["123"],
            filters: {
                status: "missing",
                search: null,
            },
        });

        dispatchEventSpy.mockRestore();
    });

    it("dispatches recognition analytics with filters and notice messaging", () => {
        (globalThis as any).ContextAltTextAdmin = {
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                    workbenchRecognition: true,
                },
            },
            data: {
                workbench: workbenchBootstrapData,
            },
        };

        const dispatchEventSpy = vi.spyOn(window, "dispatchEvent");
        render(<App />);

        const checkbox = screen.getByRole("checkbox", { name: /Select Sample image/i });
        fireEvent.click(checkbox);

        const recognitionButton = screen.getByRole("button", { name: /Trigger Recognition/i });
        fireEvent.click(recognitionButton);

        expect(dispatchNoticeMock).toHaveBeenCalledWith(
            "info",
            "Recognition triggered for 1 item.",
            expect.objectContaining({
                id: "workbench-recognition",
                spokenMessage: "Recognition triggered for 1 item.",
            }),
        );
        expect(dispatchNoticeMock).toHaveBeenCalledTimes(1);

        const recognitionEvents = dispatchEventSpy.mock.calls.filter(
            ([event]) => event.type === "cat_workbench_recognition_triggered",
        );
        expect(recognitionEvents).toHaveLength(1);
        const [recognitionEvent] = recognitionEvents[0];
        expect(recognitionEvent.detail).toMatchObject({
            count: 1,
            selection: ["123"],
            filters: {
                status: "missing",
                search: null,
            },
        });

        dispatchEventSpy.mockRestore();
    });
});
