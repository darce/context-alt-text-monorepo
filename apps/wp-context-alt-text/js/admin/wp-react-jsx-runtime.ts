import type { ReactElement } from "react";
import React from "./wp-react";

type ElementType = Parameters<typeof React.createElement>[0];

const normalizeKey = (value: unknown): string | null => {
    if (value === undefined || value === null) {
        return null;
    }

    switch (typeof value) {
        case "string":
        case "number":
        case "bigint":
        case "boolean":
            return String(value);
        default:
            return null;
    }
};

const RESERVED_PROPS = new Set(["key", "ref", "__self", "__source"]);

const prepareProps = <T extends Record<string, unknown>>(
    type: ElementType,
    config: T | null | undefined,
    maybeKey?: string,
): Record<string, unknown> => {
    const props: Record<string, unknown> = {};
    let key: string | null = null;
    let ref: unknown;

    if (maybeKey !== undefined) {
        key = String(maybeKey);
    }

    if (config) {
        if (Object.prototype.hasOwnProperty.call(config, "key")) {
            const configKey = (config as { key?: unknown }).key;
            const normalizedKey = normalizeKey(configKey);
            if (normalizedKey !== null) {
                key = normalizedKey;
            }
        }

        if (Object.prototype.hasOwnProperty.call(config, "ref")) {
            ref = config.ref;
        }

        for (const propName in config) {
            if (!RESERVED_PROPS.has(propName)) {
                props[propName] = config[propName];
            }
        }
    }

    if (type && typeof (type as { defaultProps?: Record<string, unknown> }).defaultProps === "object") {
        const defaults = (type as { defaultProps?: Record<string, unknown> }).defaultProps ?? {};
        for (const propName in defaults) {
            if (props[propName] === undefined) {
                props[propName] = defaults[propName];
            }
        }
    }

    if (ref !== undefined) {
        props.ref = ref;
    }

    if (key !== null) {
        props.key = key;
    }

    return props;
};

const createElement = (
    type: ElementType,
    config: Record<string, unknown> | null | undefined,
    maybeKey?: string,
): ReactElement => {
    const props = prepareProps(type, config, maybeKey);
    return React.createElement(type, props);
};

const jsx = (
    type: ElementType,
    config: Record<string, unknown> | null,
    maybeKey?: string,
): ReactElement => {
    return createElement(type, config ?? undefined, maybeKey);
};

const jsxs = jsx;

const jsxDEV = (
    type: ElementType,
    config: Record<string, unknown> | null,
    maybeKey?: string,
    _source?: unknown,
    _self?: unknown,
): ReactElement => {
    void _source;
    void _self;
    return createElement(type, config ?? undefined, maybeKey);
};
const Fragment = React.Fragment;

export { jsx, jsxs, jsxDEV, Fragment };

export default {
    jsx,
    jsxs,
    jsxDEV,
    Fragment,
};
