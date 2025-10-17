import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { http, HttpResponse } from "msw";
import { setAdminBootstrap } from "@/admin/globals";
import type { DashboardData, GlobalPayload, WorkbenchData } from "@/admin/types";

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
const WORKBENCH_MEDIA_ENDPOINT = "https://example.com/wp-json/cat/v1/workbench/media";
const WORKBENCH_MEDIA_FALLBACK_PATH = "/wp-json/cat/v1/workbench/media";
const WORKBENCH_MEDIA_FALLBACK_HANDLER = `*${WORKBENCH_MEDIA_FALLBACK_PATH}`;

const wait = async (ms: number) => {
    await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, ms));
    });
};

const bootstrapPayload: DashboardData = {
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
        roster_pending: 0,
        roster_conflicts: 0,
        roster_total: 0,
        last_roster_sync_human: null,
        last_roster_sync_at: null,
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

const workbenchBootstrapData: WorkbenchData = {
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

const baseBootstrapPayload: GlobalPayload = {
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

describe("App", () => {
    beforeEach(() => {
        dispatchNoticeMock.mockReset();
        notifyErrorMock.mockReset();

        setAdminBootstrap(baseBootstrapPayload);

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
        setAdminBootstrap(undefined);
    });

    it("hydrates the dashboard and passes accessibility checks", async () => {
        const { container } = render(<App />);

        expect(screen.getByText(/We found 12 images missing alt text/i)).toBeInTheDocument();

        await screen.findByRole("img", { name: /Coverage 70%/i });

        const results = await axe(container);
        expect(results.violations).toHaveLength(0);
    });

    it("hydrates the workbench bootstrap payload and passes accessibility checks", async () => {
        setAdminBootstrap({
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
        });

        const { container } = render(<App />);

        await screen.findByRole("table", { name: /Media queue/i });
        await screen.findByRole("button", { name: /Generate Alt Text/i });

        const results = await axe(container);
        expect(results.violations).toHaveLength(0);
    });

    it("renders the workbench when requested", () => {
        setAdminBootstrap({
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                    workbenchRecognition: true,
                    workbenchBulkAI: true,
                },
                endpoints: {
                    workbenchMedia: "https://example.com/wp-json/cat/v1/workbench/media",
                },
            },
            data: {
                workbench: workbenchBootstrapData,
            },
        });

        const { getByText } = render(<App />);

        expect(getByText(/Sample image/i)).toBeInTheDocument();
        expect(getByText(/image\/jpeg/i)).toBeInTheDocument();
        expect(screen.getByRole("table", { name: /Media queue/i })).toBeInTheDocument();
    });

    it("hydrates the workbench route from bootstrap data", () => {
        setAdminBootstrap({
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                },
            },
            data: {
                workbench: {
                    ...workbenchBootstrapData,
                    items: [
                        ...workbenchBootstrapData.items,
                        {
                            id: "456",
                            title: "Second asset",
                            status: "draft" as const,
                            updatedAt: "2024-04-04T00:00:00.000Z",
                            altText: "Draft alt text",
                            mimeType: "image/png",
                            dimensions: { width: 640, height: 480 },
                            editUrl: "https://example.com/wp-admin/post.php?post=456&action=edit",
                        },
                    ],
                    pagination: {
                        page: 1,
                        perPage: 20,
                        total: 2,
                        totalPages: 1,
                    },
                },
            },
        });

        render(<App />);

        expect(screen.getByRole("heading", { name: /Recognition/i })).toBeInTheDocument();
        const selectionSummary = screen.getByText((_, element) => element?.textContent === "0 items selected");
        expect(selectionSummary).toBeInTheDocument();
        expect(screen.getByRole("table", { name: /Media queue/i })).toBeInTheDocument();
        expect(screen.getByRole("combobox", { name: /Items per page/i })).toHaveValue("20");
    });

    it("passes axe accessibility checks on the workbench route", async () => {
        setAdminBootstrap({
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                },
            },
            data: {
                workbench: workbenchBootstrapData,
            },
        });

        const { container } = render(<App />);
        const results = await axe(container);
        expect(results.violations).toHaveLength(0);
    });

    it("emits workbench seen analytics once when route loads", () => {
        setAdminBootstrap({
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                },
            },
            data: {
                workbench: workbenchBootstrapData,
            },
        });

        const dispatchEventSpy = vi.spyOn(window, "dispatchEvent");
        render(<App />);

        const seenEvents = dispatchEventSpy.mock.calls.filter(([event]) => event.type === "cat_workbench_seen");
        expect(seenEvents).toHaveLength(1);
        const seenEvent = seenEvents[0]?.[0];
        expect(seenEvent).toBeInstanceOf(CustomEvent);
        const seenCustomEvent = seenEvent as CustomEvent<Record<string, unknown>>;
        expect(seenCustomEvent.detail).toMatchObject({
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

    it("filters workbench media items when searching without a REST endpoint", async () => {
        const observedRequests: URL[] = [];

        useDashboardHandlers(
            http.get(WORKBENCH_MEDIA_FALLBACK_HANDLER, ({ request }) => {
                const url = new URL(request.url);
                observedRequests.push(url);

                if (url.searchParams.get("search") === "mountain") {
                    return HttpResponse.json(
                        [
                            {
                                id: "beta",
                                title: "Mountain trail",
                                status: "missing",
                                updated_at: "2024-01-03T00:00:00.000Z",
                                alt_text: "Hikers ascending a steep trail",
                                mime_type: "image/png",
                                dimensions: { width: 1400, height: 900 },
                                edit_url: "https://example.com/edit/beta",
                            },
                        ],
                        {
                            headers: {
                                "X-WP-Total": "1",
                                "X-WP-TotalPages": "1",
                            },
                        },
                    );
                }

                return HttpResponse.json([
                    {
                        id: "alpha",
                        title: "Ocean view",
                        status: "missing",
                        updated_at: "2024-01-02T00:00:00.000Z",
                        alt_text: "A wide shot of the ocean horizon",
                        mime_type: "image/jpeg",
                        dimensions: { width: 1200, height: 800 },
                        edit_url: "https://example.com/edit/alpha",
                    },
                    {
                        id: "beta",
                        title: "Mountain trail",
                        status: "missing",
                        updated_at: "2024-01-03T00:00:00.000Z",
                        alt_text: "Hikers ascending a steep trail",
                        mime_type: "image/png",
                        dimensions: { width: 1400, height: 900 },
                        edit_url: "https://example.com/edit/beta",
                    },
                ]);
            }),
        );

        setAdminBootstrap({
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                },
            },
            data: {
                workbench: {
                    ...workbenchBootstrapData,
                    items: [
                        {
                            id: "alpha",
                            title: "Ocean view",
                            status: "missing",
                            updatedAt: "2024-01-02T00:00:00.000Z",
                            altText: "A wide shot of the ocean horizon",
                            mimeType: "image/jpeg",
                            dimensions: { width: 1200, height: 800 },
                            editUrl: "https://example.com/edit/alpha",
                        },
                        {
                            id: "beta",
                            title: "Mountain trail",
                            status: "missing",
                            updatedAt: "2024-01-03T00:00:00.000Z",
                            altText: "Hikers ascending a steep trail",
                            mimeType: "image/png",
                            dimensions: { width: 1400, height: 900 },
                            editUrl: "https://example.com/edit/beta",
                        },
                    ],
                    pagination: {
                        page: 1,
                        perPage: 20,
                        total: 2,
                        totalPages: 1,
                    },
                },
            },
        });

        const user = userEvent.setup();

        render(<App />);

        expect(await screen.findByText(/Ocean view/i)).toBeInTheDocument();
        expect(screen.getByText(/Mountain trail/i)).toBeInTheDocument();

        const input = screen.getByRole("searchbox", { name: /search media/i });
        await user.clear(input);
        await user.type(input, "mountain");

        await wait(0);

        await waitFor(() => {
            expect(
                observedRequests.some((url) => url.searchParams.get("search") === "mountain"),
            ).toBe(true);
        });

        expect(await screen.findByText(/Mountain trail/i)).toBeInTheDocument();
        expect(screen.queryByText(/Ocean view/i)).not.toBeInTheDocument();

        const statusRegion = await screen.findByTestId("workbench-search-status");
        expect(statusRegion).toHaveTextContent("Showing 1 search result.");
    });

    it("loads additional pages via the fallback workbench endpoint when pagination changes", async () => {
        const observedRequests: URL[] = [];
        const originalAjaxUrl = (window as unknown as { ajaxurl?: string }).ajaxurl;
        (window as unknown as { ajaxurl?: string }).ajaxurl = "/wp-admin/admin-ajax.php";

        useDashboardHandlers(
            http.get(WORKBENCH_MEDIA_FALLBACK_HANDLER, ({ request }) => {
                const url = new URL(request.url);
                observedRequests.push(url);

                const pageParam = url.searchParams.get("page") ?? "1";
                const payload =
                    pageParam === "1"
                        ? [
                            {
                                id: "f1",
                                title: "Fallback portrait one",
                                status: "missing",
                                updated_at: "2024-03-01T00:00:00.000Z",
                                alt_text: "",
                                mime_type: "image/jpeg",
                                dimensions: { width: 1600, height: 900 },
                                edit_url: "https://example.com/wp-admin/post.php?post=f1&action=edit",
                            },
                            {
                                id: "f2",
                                title: "Fallback portrait two",
                                status: "missing",
                                updated_at: "2024-03-02T00:00:00.000Z",
                                alt_text: "",
                                mime_type: "image/jpeg",
                                dimensions: { width: 1600, height: 900 },
                                edit_url: "https://example.com/wp-admin/post.php?post=f2&action=edit",
                            },
                        ]
                        : [
                            {
                                id: "f3",
                                title: "Fallback portrait three",
                                status: "missing",
                                updated_at: "2024-03-03T00:00:00.000Z",
                                alt_text: "",
                                mime_type: "image/jpeg",
                                dimensions: { width: 1600, height: 900 },
                                edit_url: "https://example.com/wp-admin/post.php?post=f3&action=edit",
                            },
                        ];

                return HttpResponse.json(payload, {
                    headers: {
                        "X-WP-Total": "3",
                        "X-WP-TotalPages": "2",
                    },
                });
            }),
        );

        setAdminBootstrap({
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                },
            },
            data: {
                workbench: {
                    ...workbenchBootstrapData,
                    pagination: {
                        page: 1,
                        perPage: 2,
                        total: 3,
                        totalPages: 2,
                    },
                    items: [
                        {
                            id: "f1",
                            title: "Fallback portrait one",
                            status: "missing",
                            updatedAt: "2024-03-01T00:00:00.000Z",
                            altText: "",
                            mimeType: "image/jpeg",
                            dimensions: { width: 1600, height: 900 },
                            editUrl: "https://example.com/wp-admin/post.php?post=f1&action=edit",
                        },
                        {
                            id: "f2",
                            title: "Fallback portrait two",
                            status: "missing",
                            updatedAt: "2024-03-02T00:00:00.000Z",
                            altText: "",
                            mimeType: "image/jpeg",
                            dimensions: { width: 1600, height: 900 },
                            editUrl: "https://example.com/wp-admin/post.php?post=f2&action=edit",
                        },
                    ],
                },
            },
        });

        try {
            render(<App />);

            expect(await screen.findByText(/Fallback portrait one/i)).toBeInTheDocument();
            expect(await screen.findByText("Showing 1-2 of 3")).toBeInTheDocument();

            const nextButton = screen.getByRole("button", { name: /Next/i });
            fireEvent.click(nextButton);

            await waitFor(() =>
                expect(observedRequests.some((url) => url.searchParams.get("page") === "2")).toBe(true),
            );

            expect(await screen.findByText(/Fallback portrait three/i)).toBeInTheDocument();
            expect(await screen.findByText("Showing 3-3 of 3")).toBeInTheDocument();
        } finally {
            (window as unknown as { ajaxurl?: string }).ajaxurl = originalAjaxUrl;
        }
    });

    it("allows changing items per page and refetches with the new size", async () => {
        const observedRequests: URL[] = [];

        useDashboardHandlers(
            http.get(WORKBENCH_MEDIA_FALLBACK_HANDLER, ({ request }) => {
                const url = new URL(request.url);
                observedRequests.push(url);

                const perPage = url.searchParams.get("per_page") ?? "2";
                const pageParam = url.searchParams.get("page") ?? "1";

                const buildItems = (prefix: string, count: number, offset: number) =>
                    Array.from({ length: count }, (_, index) => ({
                        id: `${prefix}-${offset + index + 1}`,
                        title: `${prefix} asset ${offset + index + 1}`,
                        status: "missing",
                        updated_at: "2024-04-0${index + 1}T00:00:00.000Z",
                        alt_text: "",
                        mime_type: "image/jpeg",
                        dimensions: { width: 1200, height: 800 },
                        edit_url: `https://example.com/wp-admin/post.php?post=${prefix}-${index + 1}&action=edit`,
                    }));

                const perPageNumber = Number(perPage);
                const pageNumber = Number(pageParam);
                const totalItems = 6;

                const start = (pageNumber - 1) * perPageNumber;
                const end = Math.min(start + perPageNumber, totalItems);

                return HttpResponse.json(buildItems("page", end - start, start), {
                    headers: {
                        "X-WP-Total": String(totalItems),
                        "X-WP-TotalPages": String(Math.ceil(totalItems / perPageNumber) || 1),
                    },
                });
            }),
        );

        setAdminBootstrap({
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                },
            },
            data: {
                workbench: {
                    ...workbenchBootstrapData,
                    pagination: {
                        page: 1,
                        perPage: 2,
                        total: 6,
                        totalPages: 3,
                    },
                    items: [
                        {
                            id: "page-1",
                            title: "Initial asset 1",
                            status: "missing",
                            updatedAt: "2024-04-01T00:00:00.000Z",
                            altText: "",
                            mimeType: "image/jpeg",
                            dimensions: { width: 1200, height: 800 },
                            editUrl: "https://example.com/wp-admin/post.php?post=page-1&action=edit",
                        },
                        {
                            id: "page-2",
                            title: "Initial asset 2",
                            status: "missing",
                            updatedAt: "2024-04-02T00:00:00.000Z",
                            altText: "",
                            mimeType: "image/jpeg",
                            dimensions: { width: 1200, height: 800 },
                            editUrl: "https://example.com/wp-admin/post.php?post=page-2&action=edit",
                        },
                    ],
                },
            },
        });

        const user = userEvent.setup();

        render(<App />);

        const select = await screen.findByLabelText(/Items per page/i);
        await user.selectOptions(select, "10");

        await waitFor(() =>
            expect(
                observedRequests.some((url) =>
                    url.searchParams.get("per_page") === "10" && url.searchParams.get("page") === "1",
                ),
            ).toBe(true),
        );

        expect(await screen.findByText(/Showing 1-6 of 6/i)).toBeInTheDocument();
        expect(screen.getByText(/Page 1/)).toBeInTheDocument();
    });

    it("dispatches notices when bulk actions are triggered", () => {
        setAdminBootstrap({
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
        });

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
        const firstBulkCall = bulkEvents[0];
        expect(firstBulkCall).toBeDefined();
        const [bulkEvent] = firstBulkCall as [Event];
        const bulkCustomEvent = bulkEvent as CustomEvent<Record<string, unknown>>;
        expect(bulkCustomEvent.detail).toMatchObject({
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

    it("filters workbench media via debounced search with inline status messaging", async () => {
        const observedRequests: URL[] = [];

        setAdminBootstrap({
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                },
                endpoints: {
                    workbenchMedia: WORKBENCH_MEDIA_ENDPOINT,
                },
            },
            data: {
                workbench: {
                    ...workbenchBootstrapData,
                    items: workbenchBootstrapData.items,
                    pagination: {
                        ...workbenchBootstrapData.pagination,
                        total: 1,
                        totalPages: 1,
                    },
                },
            },
        });

        useDashboardHandlers(
            http.get(WORKBENCH_MEDIA_ENDPOINT, async ({ request }) => {
                const url = new URL(request.url);
                observedRequests.push(url);

                expect(url.searchParams.get("search")).toBe("portrait");

                await new Promise((resolve) => setTimeout(resolve, 50));

                return HttpResponse.json(
                    [
                        {
                            id: "456",
                            title: "Portrait hero image",
                            status: "missing",
                            updated_at: "2024-02-01T00:00:00.000Z",
                            alt_text: "",
                            mime_type: "image/jpeg",
                            dimensions: { width: 1200, height: 800 },
                            edit_url: "https://example.com/wp-admin/post.php?post=456&action=edit",
                        },
                    ],
                    {
                        headers: {
                            "X-WP-Total": "1",
                            "X-WP-TotalPages": "1",
                        },
                    },
                );
            }),
        );

        render(<App />);

        const input = screen.getByRole("searchbox", { name: /search media/i });
        fireEvent.change(input, { target: { value: "portrait" } });

        await wait(0);

        await waitFor(() => {
            const spinner = screen.getByRole("status", { name: /searching media/i });
            expect(spinner).toBeInTheDocument();
        });

        await waitFor(() => {
            expect(
                observedRequests.some((url) => url.searchParams.get("search") === "portrait"),
            ).toBe(true);
        });

        expect(await screen.findByText(/Portrait hero image/i)).toBeInTheDocument();

        const statusRegion = await screen.findByTestId("workbench-search-status");
        expect(statusRegion).toHaveTextContent("Showing 1 search result.");
    });

    it("supports pagination across remote workbench pages", async () => {
        const observedRequests: URL[] = [];

        const remoteResponses: Record<string, Record<string, unknown>[]> = {
            "1": [
                {
                    id: "p1",
                    title: "First portrait",
                    status: "missing",
                    updated_at: "2024-02-10T00:00:00.000Z",
                    alt_text: "",
                    mime_type: "image/jpeg",
                    dimensions: { width: 1600, height: 900 },
                    edit_url: "https://example.com/wp-admin/post.php?post=p1&action=edit",
                },
                {
                    id: "p2",
                    title: "Second portrait",
                    status: "missing",
                    updated_at: "2024-02-11T00:00:00.000Z",
                    alt_text: "",
                    mime_type: "image/jpeg",
                    dimensions: { width: 1600, height: 900 },
                    edit_url: "https://example.com/wp-admin/post.php?post=p2&action=edit",
                },
            ],
            "2": [
                {
                    id: "p3",
                    title: "Final portrait",
                    status: "missing",
                    updated_at: "2024-02-12T00:00:00.000Z",
                    alt_text: "",
                    mime_type: "image/jpeg",
                    dimensions: { width: 1600, height: 900 },
                    edit_url: "https://example.com/wp-admin/post.php?post=p3&action=edit",
                },
            ],
        };

        useDashboardHandlers(
            http.get(WORKBENCH_MEDIA_ENDPOINT, ({ request }) => {
                const url = new URL(request.url);
                observedRequests.push(url);

                const pageParam = url.searchParams.get("page") ?? "1";
                const responseItems = remoteResponses[pageParam] ?? remoteResponses["1"];

                return HttpResponse.json(responseItems, {
                    headers: {
                        "X-WP-Total": "3",
                        "X-WP-TotalPages": "2",
                    },
                });
            }),
        );

        setAdminBootstrap({
            page: "workbench",
            config: {
                featureFlags: {
                    workbenchEnabled: true,
                },
                endpoints: {
                    workbenchMedia: WORKBENCH_MEDIA_ENDPOINT,
                },
                restNonce: "workbench-nonce",
            },
            data: {
                workbench: {
                    ...workbenchBootstrapData,
                    pagination: {
                        page: 1,
                        perPage: 2,
                        total: 3,
                        totalPages: 2,
                    },
                    items: [
                        {
                            id: "p1",
                            title: "First portrait",
                            status: "missing",
                            updatedAt: "2024-02-10T00:00:00.000Z",
                            altText: "",
                            mimeType: "image/jpeg",
                            dimensions: { width: 1600, height: 900 },
                            editUrl: "https://example.com/wp-admin/post.php?post=p1&action=edit",
                        },
                        {
                            id: "p2",
                            title: "Second portrait",
                            status: "missing",
                            updatedAt: "2024-02-11T00:00:00.000Z",
                            altText: "",
                            mimeType: "image/jpeg",
                            dimensions: { width: 1600, height: 900 },
                            editUrl: "https://example.com/wp-admin/post.php?post=p2&action=edit",
                        },
                    ],
                },
            },
        });

        render(<App />);

        expect(await screen.findByText(/First portrait/i)).toBeInTheDocument();

        const paginationNav = await screen.findByRole("navigation", { name: /Workbench pagination/i });
        expect(paginationNav).toBeInTheDocument();
        expect(screen.getByText("Showing 1-2 of 3")).toBeInTheDocument();

        const nextButton = screen.getByRole("button", { name: /Next/i });
        fireEvent.click(nextButton);

        await waitFor(() =>
            expect(observedRequests.some((url) => url.searchParams.get("page") === "2")).toBe(true),
        );

        expect(await screen.findByText(/Final portrait/i)).toBeInTheDocument();
        expect(screen.getByText("Showing 3-3 of 3")).toBeInTheDocument();

        const previousButton = screen.getByRole("button", { name: /Previous/i });
        fireEvent.click(previousButton);

        await waitFor(() =>
            expect(
                observedRequests.filter((url) => url.searchParams.get("page") === "1").length,
            ).toBeGreaterThanOrEqual(2),
        );

        expect(await screen.findByText(/First portrait/i)).toBeInTheDocument();
        expect(screen.getByText("Showing 1-2 of 3")).toBeInTheDocument();
    });
});
