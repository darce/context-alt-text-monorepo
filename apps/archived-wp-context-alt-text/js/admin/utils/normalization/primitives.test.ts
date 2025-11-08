import { describe, it, expect } from "vitest";
import {
    toFiniteNumber,
    toNumberOrNull,
    toNullableTimestamp,
    toStringOrNull,
    ensureString,
    toBooleanOrNull,
    toUniqueNumericIds,
} from "./primitives";

describe("toFiniteNumber", () => {
    it("converts valid numbers to numbers", () => {
        expect(toFiniteNumber(42)).toBe(42);
        expect(toFiniteNumber(0)).toBe(0);
        expect(toFiniteNumber(-10)).toBe(-10);
        expect(toFiniteNumber(3.14)).toBe(3.14);
    });

    it("converts numeric strings to numbers", () => {
        expect(toFiniteNumber("42")).toBe(42);
        expect(toFiniteNumber("0")).toBe(0);
        expect(toFiniteNumber("-10")).toBe(-10);
        expect(toFiniteNumber("3.14")).toBe(3.14);
    });

    it("returns default fallback for invalid values", () => {
        expect(toFiniteNumber(null)).toBe(0);
        expect(toFiniteNumber(undefined)).toBe(0);
        expect(toFiniteNumber("not a number")).toBe(0);
        expect(toFiniteNumber(NaN)).toBe(0);
        expect(toFiniteNumber(Infinity)).toBe(0);
        expect(toFiniteNumber(-Infinity)).toBe(0);
        expect(toFiniteNumber({})).toBe(0);
        expect(toFiniteNumber([])).toBe(0);
    });

    it("returns custom fallback when provided", () => {
        // Note: Number(null) = 0, which is finite, so it returns 0, not the fallback
        // The fallback is only used when the result is NOT finite (NaN, Infinity, -Infinity)
        expect(toFiniteNumber(undefined, 100)).toBe(100); // Number(undefined) = NaN
        expect(toFiniteNumber("invalid", 42)).toBe(42); // Number("invalid") = NaN
        expect(toFiniteNumber(Infinity, 999)).toBe(999);
        expect(toFiniteNumber(-Infinity, -1)).toBe(-1);
    });

    it("handles boolean values", () => {
        expect(toFiniteNumber(true)).toBe(1);
        expect(toFiniteNumber(false)).toBe(0);
    });

    it("handles edge cases", () => {
        expect(toFiniteNumber("")).toBe(0); // Empty string converts to 0
        expect(toFiniteNumber("   ")).toBe(0); // Whitespace converts to 0
        expect(toFiniteNumber("0")).toBe(0);
        expect(toFiniteNumber("-0")).toBe(-0); // -0 is a valid finite number in JavaScript
        expect(toFiniteNumber(null)).toBe(0); // Number(null) = 0
    });
});

describe("toNumberOrNull", () => {
    it("converts valid numbers to numbers", () => {
        expect(toNumberOrNull(42)).toBe(42);
        expect(toNumberOrNull(0)).toBe(0);
        expect(toNumberOrNull(-10)).toBe(-10);
        expect(toNumberOrNull(3.14)).toBe(3.14);
    });

    it("converts numeric strings to numbers", () => {
        expect(toNumberOrNull("42")).toBe(42);
        expect(toNumberOrNull("0")).toBe(0);
        expect(toNumberOrNull("-10")).toBe(-10);
        expect(toNumberOrNull("3.14")).toBe(3.14);
    });

    it("returns null for invalid values", () => {
        // Note: Number(null) = 0, Number([]) = 0, which are finite, so they return 0, not null
        expect(toNumberOrNull(null)).toBe(0); // Number(null) = 0
        expect(toNumberOrNull(undefined)).toBeNull(); // Number(undefined) = NaN
        expect(toNumberOrNull("not a number")).toBeNull();
        expect(toNumberOrNull(NaN)).toBeNull();
        expect(toNumberOrNull(Infinity)).toBeNull();
        expect(toNumberOrNull(-Infinity)).toBeNull();
        expect(toNumberOrNull({})).toBeNull(); // Number({}) = NaN
        expect(toNumberOrNull([])).toBe(0); // Number([]) = 0
    });

    it("handles boolean values", () => {
        expect(toNumberOrNull(true)).toBe(1);
        expect(toNumberOrNull(false)).toBe(0);
    });

    it("handles edge cases", () => {
        expect(toNumberOrNull("")).toBe(0); // Empty string converts to 0
        expect(toNumberOrNull("   ")).toBe(0); // Whitespace converts to 0
        expect(toNumberOrNull("0")).toBe(0);
        expect(toNumberOrNull("-0")).toBe(-0); // -0 is a valid finite number
        expect(toNumberOrNull(null)).toBe(0); // Number(null) = 0
    });

    it("handles very large and very small numbers", () => {
        expect(toNumberOrNull(Number.MAX_SAFE_INTEGER)).toBe(Number.MAX_SAFE_INTEGER);
        expect(toNumberOrNull(Number.MIN_SAFE_INTEGER)).toBe(Number.MIN_SAFE_INTEGER);
        expect(toNumberOrNull(1e-10)).toBe(1e-10);
    });
});

describe("toNullableTimestamp", () => {
    it("converts positive numbers to timestamps", () => {
        expect(toNullableTimestamp(1)).toBe(1);
        expect(toNullableTimestamp(1000)).toBe(1000);
        expect(toNullableTimestamp(1700000000)).toBe(1700000000);
        expect(toNullableTimestamp(3.14)).toBe(3.14);
    });

    it("converts positive numeric strings to timestamps", () => {
        expect(toNullableTimestamp("1")).toBe(1);
        expect(toNullableTimestamp("1000")).toBe(1000);
        expect(toNullableTimestamp("1700000000")).toBe(1700000000);
    });

    it("returns null for zero", () => {
        expect(toNullableTimestamp(0)).toBeNull();
        expect(toNullableTimestamp("0")).toBeNull();
        expect(toNullableTimestamp("-0")).toBeNull();
    });

    it("returns null for negative numbers", () => {
        expect(toNullableTimestamp(-1)).toBeNull();
        expect(toNullableTimestamp(-100)).toBeNull();
        expect(toNullableTimestamp("-10")).toBeNull();
    });

    it("returns null for invalid values", () => {
        expect(toNullableTimestamp(null)).toBeNull();
        expect(toNullableTimestamp(undefined)).toBeNull();
        expect(toNullableTimestamp("not a number")).toBeNull();
        expect(toNullableTimestamp(NaN)).toBeNull();
        expect(toNullableTimestamp(Infinity)).toBeNull();
        expect(toNullableTimestamp(-Infinity)).toBeNull();
    });

    it("handles edge cases", () => {
        expect(toNullableTimestamp("")).toBeNull();
        expect(toNullableTimestamp("   ")).toBeNull();
        expect(toNullableTimestamp(true)).toBe(1); // true converts to 1
        expect(toNullableTimestamp(false)).toBeNull(); // false converts to 0
    });
});

describe("toStringOrNull", () => {
    it("returns trimmed non-empty strings", () => {
        expect(toStringOrNull("hello")).toBe("hello");
        expect(toStringOrNull("  hello  ")).toBe("hello");
        expect(toStringOrNull("Hello World")).toBe("Hello World");
    });

    it("returns null for empty or whitespace-only strings", () => {
        expect(toStringOrNull("")).toBeNull();
        expect(toStringOrNull("   ")).toBeNull();
        expect(toStringOrNull("\t\n")).toBeNull();
    });

    it("returns null for null and undefined", () => {
        expect(toStringOrNull(null)).toBeNull();
        expect(toStringOrNull(undefined)).toBeNull();
    });

    it("converts numbers to strings", () => {
        expect(toStringOrNull(42)).toBe("42");
        expect(toStringOrNull(0)).toBe("0");
        expect(toStringOrNull(-10)).toBe("-10");
        expect(toStringOrNull(3.14)).toBe("3.14");
    });

    it("converts booleans to strings", () => {
        expect(toStringOrNull(true)).toBe("true");
        expect(toStringOrNull(false)).toBe("false");
    });

    it("returns null for objects and arrays", () => {
        expect(toStringOrNull({})).toBeNull();
        expect(toStringOrNull([])).toBeNull();
        expect(toStringOrNull({ key: "value" })).toBeNull();
        expect(toStringOrNull([1, 2, 3])).toBeNull();
    });

    it("handles edge cases", () => {
        // NaN, Infinity, -Infinity are numbers, so they get converted to strings
        expect(toStringOrNull(NaN)).toBe("NaN");
        expect(toStringOrNull(Infinity)).toBe("Infinity");
        expect(toStringOrNull(-Infinity)).toBe("-Infinity");
    });
});

describe("ensureString", () => {
    it("returns strings as-is without trimming", () => {
        expect(ensureString("hello")).toBe("hello");
        expect(ensureString("  hello  ")).toBe("  hello  ");
        expect(ensureString("")).toBe("");
        expect(ensureString("   ")).toBe("   ");
    });

    it("returns empty string for null and undefined", () => {
        expect(ensureString(null)).toBe("");
        expect(ensureString(undefined)).toBe("");
    });

    it("converts numbers to strings", () => {
        expect(ensureString(42)).toBe("42");
        expect(ensureString(0)).toBe("0");
        expect(ensureString(-10)).toBe("-10");
        expect(ensureString(3.14)).toBe("3.14");
        expect(ensureString(NaN)).toBe("NaN");
        expect(ensureString(Infinity)).toBe("Infinity");
        expect(ensureString(-Infinity)).toBe("-Infinity");
    });

    it("converts booleans to strings", () => {
        expect(ensureString(true)).toBe("true");
        expect(ensureString(false)).toBe("false");
    });

    it("converts bigint to strings", () => {
        expect(ensureString(BigInt(42))).toBe("42");
        expect(ensureString(BigInt(9007199254740991))).toBe("9007199254740991");
    });

    it("converts Date objects to ISO strings", () => {
        const date = new Date("2023-01-15T12:00:00.000Z");
        expect(ensureString(date)).toBe("2023-01-15T12:00:00.000Z");
    });

    it("returns empty string for objects and arrays", () => {
        expect(ensureString({})).toBe("");
        expect(ensureString([])).toBe("");
        expect(ensureString({ key: "value" })).toBe("");
        expect(ensureString([1, 2, 3])).toBe("");
    });

    it("returns empty string for functions", () => {
        expect(ensureString(() => {})).toBe("");
        expect(ensureString(function test() {})).toBe("");
    });

    it("returns empty string for symbols", () => {
        expect(ensureString(Symbol("test"))).toBe("");
    });
});

describe("toBooleanOrNull", () => {
    it("returns booleans as-is", () => {
        expect(toBooleanOrNull(true)).toBe(true);
        expect(toBooleanOrNull(false)).toBe(false);
    });

    it("returns null for null and undefined", () => {
        expect(toBooleanOrNull(null)).toBeNull();
        expect(toBooleanOrNull(undefined)).toBeNull();
    });

    it("converts numbers to booleans", () => {
        expect(toBooleanOrNull(1)).toBe(true);
        expect(toBooleanOrNull(42)).toBe(true);
        expect(toBooleanOrNull(-1)).toBe(true);
        expect(toBooleanOrNull(0)).toBe(false);
        expect(toBooleanOrNull(-0)).toBe(false);
    });

    it("converts truthy string values to true", () => {
        expect(toBooleanOrNull("true")).toBe(true);
        expect(toBooleanOrNull("TRUE")).toBe(true);
        expect(toBooleanOrNull("True")).toBe(true);
        expect(toBooleanOrNull("1")).toBe(true);
        expect(toBooleanOrNull("yes")).toBe(true);
        expect(toBooleanOrNull("YES")).toBe(true);
        expect(toBooleanOrNull("Yes")).toBe(true);
    });

    it("converts falsy string values to false", () => {
        expect(toBooleanOrNull("false")).toBe(false);
        expect(toBooleanOrNull("FALSE")).toBe(false);
        expect(toBooleanOrNull("False")).toBe(false);
        expect(toBooleanOrNull("0")).toBe(false);
        expect(toBooleanOrNull("no")).toBe(false);
        expect(toBooleanOrNull("NO")).toBe(false);
        expect(toBooleanOrNull("No")).toBe(false);
        expect(toBooleanOrNull("")).toBe(false);
    });

    it("trims whitespace from string values", () => {
        expect(toBooleanOrNull("  true  ")).toBe(true);
        expect(toBooleanOrNull("  false  ")).toBe(false);
        expect(toBooleanOrNull("  1  ")).toBe(true);
        expect(toBooleanOrNull("  0  ")).toBe(false);
        expect(toBooleanOrNull("  yes  ")).toBe(true);
        expect(toBooleanOrNull("  no  ")).toBe(false);
    });

    it("returns null for ambiguous string values", () => {
        expect(toBooleanOrNull("maybe")).toBeNull();
        expect(toBooleanOrNull("2")).toBeNull();
        expect(toBooleanOrNull("on")).toBeNull();
        expect(toBooleanOrNull("off")).toBeNull();
        expect(toBooleanOrNull("hello")).toBeNull();
    });

    it("returns null for objects and arrays", () => {
        expect(toBooleanOrNull({})).toBeNull();
        expect(toBooleanOrNull([])).toBeNull();
        expect(toBooleanOrNull({ key: "value" })).toBeNull();
        expect(toBooleanOrNull([1, 2, 3])).toBeNull();
    });

    it("handles edge cases", () => {
        // NaN is typeof "number" and NaN !== 0 evaluates to true, so it returns true
        expect(toBooleanOrNull(NaN)).toBe(true);
        expect(toBooleanOrNull(Infinity)).toBe(true); // Infinity is a number != 0
        expect(toBooleanOrNull(-Infinity)).toBe(true);
    });
});

describe("toUniqueNumericIds", () => {
    it("returns array of numeric IDs unchanged", () => {
        expect(toUniqueNumericIds([1, 2, 3])).toEqual([1, 2, 3]);
        expect(toUniqueNumericIds([42])).toEqual([42]);
    });

    it("converts string IDs to numbers", () => {
        expect(toUniqueNumericIds(["1", "2", "3"])).toEqual([1, 2, 3]);
        expect(toUniqueNumericIds(["42"])).toEqual([42]);
    });

    it("handles mixed numeric and string IDs", () => {
        expect(toUniqueNumericIds([1, "2", 3, "4"])).toEqual([1, 2, 3, 4]);
    });

    it("removes duplicate values", () => {
        expect(toUniqueNumericIds([1, 2, 2, 3, 3, 3])).toEqual([1, 2, 3]);
        expect(toUniqueNumericIds(["1", "2", "2", "3"])).toEqual([1, 2, 3]);
        expect(toUniqueNumericIds([1, "1", 2, "2"])).toEqual([1, 2]);
    });

    it("filters out zero", () => {
        expect(toUniqueNumericIds([0, 1, 2])).toEqual([1, 2]);
        expect(toUniqueNumericIds(["0", "1", "2"])).toEqual([1, 2]);
        expect(toUniqueNumericIds([0])).toEqual([]);
    });

    it("filters out negative numbers", () => {
        expect(toUniqueNumericIds([-1, 1, 2])).toEqual([1, 2]);
        expect(toUniqueNumericIds(["-5", "1", "2"])).toEqual([1, 2]);
        expect(toUniqueNumericIds([-1, -2, -3])).toEqual([]);
    });

    it("filters out invalid values", () => {
        expect(toUniqueNumericIds([NaN, 1, 2])).toEqual([1, 2]);
        expect(toUniqueNumericIds([Infinity, 1, 2])).toEqual([1, 2]);
        expect(toUniqueNumericIds([-Infinity, 1, 2])).toEqual([1, 2]);
        expect(toUniqueNumericIds(["invalid", "1", "2"])).toEqual([1, 2]);
    });

    it("handles empty array", () => {
        expect(toUniqueNumericIds([])).toEqual([]);
    });

    it("handles array with only invalid values", () => {
        expect(toUniqueNumericIds([0, -1, NaN, "invalid"])).toEqual([]);
        expect(toUniqueNumericIds(["", "abc", "-5"])).toEqual([]);
    });

    it("preserves order of first occurrence", () => {
        expect(toUniqueNumericIds([3, 1, 2, 1, 3])).toEqual([3, 1, 2]);
        expect(toUniqueNumericIds(["3", "1", "2", "1", "3"])).toEqual([3, 1, 2]);
    });

    it("handles decimal numbers by converting them", () => {
        // Numbers with decimals are still valid, just converted
        expect(toUniqueNumericIds([1.5, 2.7, 3.9])).toEqual([1.5, 2.7, 3.9]);
        expect(toUniqueNumericIds(["1.5", "2.7"])).toEqual([1.5, 2.7]);
    });

    it("handles very large ID values", () => {
        const largeId = 9007199254740991; // Number.MAX_SAFE_INTEGER
        expect(toUniqueNumericIds([largeId, 1, 2])).toEqual([largeId, 1, 2]);
        expect(toUniqueNumericIds([String(largeId), "1"])).toEqual([largeId, 1]);
    });
});
