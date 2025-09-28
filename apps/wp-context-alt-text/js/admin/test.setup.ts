import "@testing-library/jest-dom/vitest";
import "@/admin/testing/mswServer";
import { toHaveNoViolations } from "vitest-axe/matchers";

expect.extend({
    toHaveNoViolations,
});

if (typeof HTMLCanvasElement !== "undefined") {
    HTMLCanvasElement.prototype.getContext = (() => null) as any;
}
