import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { buildApiUrl, buildHeaders, fetchApi, handleJsonResponse, ensureOk } from "./http";

describe("buildApiUrl", () => {
    beforeEach(() => {
        // Mock window.location.origin
        Object.defineProperty(window, "location", {
            value: {
                origin: "http://example.test",
            },
            writable: true,
        });
    });

    it("builds URL without query parameters", () => {
        const url = buildApiUrl("/wp-json/cat/v1/test");
        expect(url).toBe("http://example.test/wp-json/cat/v1/test");
    });

    it("builds URL with single query parameter", () => {
        const url = buildApiUrl("/wp-json/cat/v1/test", { id: "123" });
        expect(url).toBe("http://example.test/wp-json/cat/v1/test?id=123");
    });

    it("builds URL with multiple query parameters", () => {
        const url = buildApiUrl("/wp-json/cat/v1/test", {
            id: "123",
            status: "active",
            page: 2,
        });
        expect(url).toBe("http://example.test/wp-json/cat/v1/test?id=123&status=active&page=2");
    });

    it("filters out null values from query parameters", () => {
        const url = buildApiUrl("/wp-json/cat/v1/test", {
            id: "123",
            name: null,
            status: "active",
        });
        expect(url).toBe("http://example.test/wp-json/cat/v1/test?id=123&status=active");
    });

    it("filters out undefined values from query parameters", () => {
        const url = buildApiUrl("/wp-json/cat/v1/test", {
            id: "123",
            name: undefined,
            status: "active",
        });
        expect(url).toBe("http://example.test/wp-json/cat/v1/test?id=123&status=active");
    });

    it("converts number parameters to strings", () => {
        const url = buildApiUrl("/wp-json/cat/v1/test", {
            page: 5,
            perPage: 20,
        });
        expect(url).toBe("http://example.test/wp-json/cat/v1/test?page=5&perPage=20");
    });

    it("converts boolean parameters to strings", () => {
        const url = buildApiUrl("/wp-json/cat/v1/test", {
            enabled: true,
            archived: false,
        });
        expect(url).toBe("http://example.test/wp-json/cat/v1/test?enabled=true&archived=false");
    });

    it("properly encodes special characters in parameters", () => {
        const url = buildApiUrl("/wp-json/cat/v1/test", {
            search: "hello world",
            email: "test@example.com",
        });
        expect(url).toBe("http://example.test/wp-json/cat/v1/test?search=hello+world&email=test%40example.com");
    });

    it("handles empty params object", () => {
        const url = buildApiUrl("/wp-json/cat/v1/test", {});
        expect(url).toBe("http://example.test/wp-json/cat/v1/test");
    });

    it("handles params with only null/undefined values", () => {
        const url = buildApiUrl("/wp-json/cat/v1/test", {
            name: null,
            status: undefined,
        });
        expect(url).toBe("http://example.test/wp-json/cat/v1/test");
    });

    it("handles zero as a valid parameter value", () => {
        const url = buildApiUrl("/wp-json/cat/v1/test", {
            page: 0,
            count: 0,
        });
        expect(url).toBe("http://example.test/wp-json/cat/v1/test?page=0&count=0");
    });

    it("handles empty string as a valid parameter value", () => {
        const url = buildApiUrl("/wp-json/cat/v1/test", {
            search: "",
        });
        expect(url).toBe("http://example.test/wp-json/cat/v1/test?search=");
    });
});

describe("buildHeaders", () => {
    it("builds empty headers when no nonce provided", () => {
        const headers = buildHeaders();
        expect(headers).toEqual({});
    });

    it("includes X-WP-Nonce header when nonce provided", () => {
        const headers = buildHeaders("test-nonce-123");
        expect(headers).toEqual({
            "X-WP-Nonce": "test-nonce-123",
        });
    });

    it("includes Content-Type when includeJson is true", () => {
        const headers = buildHeaders(undefined, true);
        expect(headers).toEqual({
            "Content-Type": "application/json",
        });
    });

    it("includes both nonce and Content-Type when both provided", () => {
        const headers = buildHeaders("test-nonce-123", true);
        expect(headers).toEqual({
            "X-WP-Nonce": "test-nonce-123",
            "Content-Type": "application/json",
        });
    });

    it("excludes Content-Type when includeJson is false", () => {
        const headers = buildHeaders("test-nonce-123", false);
        expect(headers).toEqual({
            "X-WP-Nonce": "test-nonce-123",
        });
    });

    it("handles empty string nonce", () => {
        const headers = buildHeaders("");
        expect(headers).toEqual({});
    });
});

describe("handleJsonResponse", () => {
    it("returns empty object for 204 No Content response", async () => {
        const response = new Response(null, {
            status: 204,
            headers: { "Content-Type": "application/json" },
        });

        const result = await handleJsonResponse(response);
        expect(result).toEqual({});
    });

    it("parses JSON response with application/json content type", async () => {
        const data = { message: "success", id: 123 };
        const response = new Response(JSON.stringify(data), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });

        const result = await handleJsonResponse(response);
        expect(result).toEqual(data);
    });

    it("parses JSON response with application/json; charset=utf-8 content type", async () => {
        const data = { name: "Test" };
        const response = new Response(JSON.stringify(data), {
            status: 200,
            headers: { "Content-Type": "application/json; charset=utf-8" },
        });

        const result = await handleJsonResponse(response);
        expect(result).toEqual(data);
    });

    it("attempts to parse text as JSON when content type is not JSON", async () => {
        const data = { value: "test" };
        const response = new Response(JSON.stringify(data), {
            status: 200,
            headers: { "Content-Type": "text/plain" },
        });

        const result = await handleJsonResponse(response);
        expect(result).toEqual(data);
    });

    it("returns empty object when text is not valid JSON", async () => {
        const response = new Response("This is not JSON", {
            status: 200,
            headers: { "Content-Type": "text/html" },
        });

        const result = await handleJsonResponse(response);
        expect(result).toEqual({});
    });

    it("handles empty response body", async () => {
        // Empty string is not valid JSON, so it should fall back to text parsing
        // and return empty object when JSON.parse fails
        const response = new Response("", {
            status: 200,
            headers: { "Content-Type": "text/plain" },
        });

        const result = await handleJsonResponse(response);
        expect(result).toEqual({});
    });

    it("handles response without Content-Type header", async () => {
        const data = { key: "value" };
        const response = new Response(JSON.stringify(data), {
            status: 200,
        });

        const result = await handleJsonResponse(response);
        expect(result).toEqual(data);
    });
});

describe("ensureOk", () => {
    it("returns response when status is ok (2xx)", async () => {
        const response = new Response(JSON.stringify({ success: true }), {
            status: 200,
        });

        const result = await ensureOk(response);
        expect(result).toBe(response);
    });

    it("returns response for 201 Created", async () => {
        const response = new Response(JSON.stringify({ id: 123 }), {
            status: 201,
        });

        const result = await ensureOk(response);
        expect(result).toBe(response);
    });

    it("throws error with message from response data on 4xx error", async () => {
        const errorData = {
            code: "invalid_request",
            message: "Invalid attachment ID",
            data: { status: 400 },
        };

        const response = new Response(JSON.stringify(errorData), {
            status: 400,
            headers: { "Content-Type": "application/json" },
        });

        await expect(ensureOk(response)).rejects.toThrow("Invalid attachment ID");
    });

    it("throws error with message from response data on 5xx error", async () => {
        const errorData = {
            message: "Internal server error",
        };

        const response = new Response(JSON.stringify(errorData), {
            status: 500,
            headers: { "Content-Type": "application/json" },
        });

        await expect(ensureOk(response)).rejects.toThrow("Internal server error");
    });

    it("throws error with status when no message in response data", async () => {
        const response = new Response(JSON.stringify({ code: "error" }), {
            status: 404,
            headers: { "Content-Type": "application/json" },
        });

        await expect(ensureOk(response)).rejects.toThrow("Request failed with status 404");
    });

    it("attaches response data to error object", async () => {
        const errorData = {
            code: "rest_invalid_param",
            message: "Invalid parameter",
            data: { status: 400, params: { id: "Invalid ID" } },
        };

        const response = new Response(JSON.stringify(errorData), {
            status: 400,
            headers: { "Content-Type": "application/json" },
        });

        try {
            await ensureOk(response);
            expect.fail("Should have thrown");
        } catch (error) {
            expect(error).toBeInstanceOf(Error);
            expect((error as Error & { data: unknown }).data).toEqual(errorData);
        }
    });

    it("handles non-JSON error response", async () => {
        const response = new Response("Server Error", {
            status: 500,
            headers: { "Content-Type": "text/html" },
        });

        await expect(ensureOk(response)).rejects.toThrow("Request failed with status 500");
    });
});

describe("fetchApi", () => {
    let fetchMock: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        Object.defineProperty(window, "location", {
            value: {
                origin: "http://example.test",
            },
            writable: true,
        });

        fetchMock = vi.fn();
        global.fetch = fetchMock;
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it("makes GET request to endpoint", async () => {
        const responseData = { id: 123, name: "Test" };
        fetchMock.mockResolvedValueOnce(
            new Response(JSON.stringify(responseData), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );

        const result = await fetchApi("/wp-json/cat/v1/test");

        expect(fetchMock).toHaveBeenCalledWith("http://example.test/wp-json/cat/v1/test", {
            method: "GET",
            headers: {},
        });
        expect(result).toEqual(responseData);
    });

    it("makes POST request with JSON body", async () => {
        const requestBody = { name: "New Item", value: 42 };
        const responseData = { id: 456, ...requestBody };

        fetchMock.mockResolvedValueOnce(
            new Response(JSON.stringify(responseData), {
                status: 201,
                headers: { "Content-Type": "application/json" },
            }),
        );

        const result = await fetchApi("/wp-json/cat/v1/test", {
            method: "POST",
            body: requestBody,
        });

        expect(fetchMock).toHaveBeenCalledWith("http://example.test/wp-json/cat/v1/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestBody),
        });
        expect(result).toEqual(responseData);
    });

    it("includes REST nonce in headers", async () => {
        fetchMock.mockResolvedValueOnce(
            new Response(JSON.stringify({ success: true }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );

        await fetchApi("/wp-json/cat/v1/test", {
            restNonce: "nonce-123",
        });

        expect(fetchMock).toHaveBeenCalledWith("http://example.test/wp-json/cat/v1/test", {
            method: "GET",
            headers: { "X-WP-Nonce": "nonce-123" },
        });
    });

    it("appends query parameters to URL", async () => {
        fetchMock.mockResolvedValueOnce(
            new Response(JSON.stringify({ items: [] }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );

        await fetchApi("/wp-json/cat/v1/test", {
            params: { page: 2, per_page: 10, search: "test" },
        });

        expect(fetchMock).toHaveBeenCalledWith(
            "http://example.test/wp-json/cat/v1/test?page=2&per_page=10&search=test",
            expect.objectContaining({ method: "GET" }),
        );
    });

    it("filters null/undefined params before making request", async () => {
        fetchMock.mockResolvedValueOnce(
            new Response(JSON.stringify({ items: [] }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );

        await fetchApi("/wp-json/cat/v1/test", {
            params: {
                status: "active",
                name: null,
                page: undefined,
            },
        });

        expect(fetchMock).toHaveBeenCalledWith(
            "http://example.test/wp-json/cat/v1/test?status=active",
            expect.objectContaining({ method: "GET" }),
        );
    });

    it("makes PATCH request with body", async () => {
        const updateData = { status: "active" };
        fetchMock.mockResolvedValueOnce(
            new Response(JSON.stringify({ ...updateData, id: 789 }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );

        await fetchApi("/wp-json/cat/v1/test/789", {
            method: "PATCH",
            body: updateData,
        });

        expect(fetchMock).toHaveBeenCalledWith("http://example.test/wp-json/cat/v1/test/789", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(updateData),
        });
    });

    it("makes DELETE request", async () => {
        fetchMock.mockResolvedValueOnce(
            new Response(JSON.stringify({ deleted: true }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );

        await fetchApi("/wp-json/cat/v1/test/999", {
            method: "DELETE",
        });

        expect(fetchMock).toHaveBeenCalledWith("http://example.test/wp-json/cat/v1/test/999", {
            method: "DELETE",
            headers: {},
        });
    });

    it("does not include body for GET requests even if body provided", async () => {
        fetchMock.mockResolvedValueOnce(
            new Response(JSON.stringify({ data: [] }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );

        await fetchApi("/wp-json/cat/v1/test", {
            method: "GET",
            body: { shouldBeIgnored: true },
        });

        expect(fetchMock).toHaveBeenCalledWith(
            "http://example.test/wp-json/cat/v1/test",
            expect.objectContaining({
                method: "GET",
                headers: {},
            }),
        );

        const callArgs = fetchMock.mock.calls[0] as [string, RequestInit];
        expect(callArgs[1].body).toBeUndefined();
    });

    it("handles string body directly without JSON encoding", async () => {
        const stringBody = "raw string data";
        fetchMock.mockResolvedValueOnce(
            new Response(JSON.stringify({ received: true }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );

        await fetchApi("/wp-json/cat/v1/test", {
            method: "POST",
            body: stringBody,
        });

        expect(fetchMock).toHaveBeenCalledWith("http://example.test/wp-json/cat/v1/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: stringBody,
        });
    });

    it("throws error on non-ok response", async () => {
        fetchMock.mockResolvedValueOnce(
            new Response(
                JSON.stringify({
                    code: "rest_forbidden",
                    message: "Sorry, you are not allowed to do that.",
                    data: { status: 403 },
                }),
                {
                    status: 403,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        );

        await expect(fetchApi("/wp-json/cat/v1/test")).rejects.toThrow("Sorry, you are not allowed to do that.");
    });

    it("handles 204 No Content response", async () => {
        fetchMock.mockResolvedValueOnce(
            new Response(null, {
                status: 204,
            }),
        );

        const result = await fetchApi("/wp-json/cat/v1/test", {
            method: "DELETE",
        });

        expect(result).toEqual({});
    });

    it("combines nonce, params, and body in single request", async () => {
        const requestBody = { name: "Updated" };
        fetchMock.mockResolvedValueOnce(
            new Response(JSON.stringify({ success: true }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );

        await fetchApi("/wp-json/cat/v1/test", {
            method: "POST",
            params: { id: "123", action: "update" },
            body: requestBody,
            restNonce: "secure-nonce",
        });

        expect(fetchMock).toHaveBeenCalledWith("http://example.test/wp-json/cat/v1/test?id=123&action=update", {
            method: "POST",
            headers: {
                "X-WP-Nonce": "secure-nonce",
                "Content-Type": "application/json",
            },
            body: JSON.stringify(requestBody),
        });
    });

    it("returns typed response based on generic parameter", async () => {
        interface TestResponse {
            id: number;
            name: string;
            active: boolean;
        }

        const responseData: TestResponse = {
            id: 42,
            name: "Typed Response",
            active: true,
        };

        fetchMock.mockResolvedValueOnce(
            new Response(JSON.stringify(responseData), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );

        const result = await fetchApi<TestResponse>("/wp-json/cat/v1/test");

        // TypeScript should recognize the typed properties
        expect(result.id).toBe(42);
        expect(result.name).toBe("Typed Response");
        expect(result.active).toBe(true);
    });
});
