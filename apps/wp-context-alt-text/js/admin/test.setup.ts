import { expect } from "vitest";
import "@testing-library/jest-dom/vitest";
import "@/admin/testing/mswServer";
import * as matchers from "vitest-axe/matchers";

expect.extend(matchers);

if (typeof HTMLCanvasElement !== "undefined") {
    const canvasContextStub = function canvasContextStub(
        this: HTMLCanvasElement,
        contextId: string,
        options?: CanvasRenderingContext2DSettings,
    ): null {
        void contextId;
        void options;
        return null;
    };

    HTMLCanvasElement.prototype.getContext = canvasContextStub as HTMLCanvasElement["getContext"];
}

// Polyfills for Radix UI pointer events (jsdom doesn't implement these)
if (typeof Element !== "undefined") {
    if (!Element.prototype.hasPointerCapture) {
        Element.prototype.hasPointerCapture = function () {
            return false;
        };
    }
    if (!Element.prototype.setPointerCapture) {
        Element.prototype.setPointerCapture = function () {
            // no-op
        };
    }
    if (!Element.prototype.releasePointerCapture) {
        Element.prototype.releasePointerCapture = function () {
            // no-op
        };
    }

    // Polyfill for scrollIntoView (jsdom has limited support)
    if (!Element.prototype.scrollIntoView) {
        Element.prototype.scrollIntoView = function () {
            // no-op
        };
    }
}
