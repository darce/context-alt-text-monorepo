import { afterAll, afterEach, beforeAll } from "vitest";
import { setupServer } from "msw/node";
import type { RestHandler } from "msw";

export const server = setupServer();

export const useDashboardHandlers = (...handlers: RestHandler[]) => {
    server.use(...handlers);
};

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));

afterEach(() => {
    server.resetHandlers();
});

afterAll(() => {
    server.close();
});
