type ReactExports = typeof import("react");

type WordPressRuntime = ReactExports & Record<string, unknown>;

type GlobalWithWP = typeof globalThis & {
    wp?: {
        element?: unknown;
    };
};

const resolveWordPressElement = (): WordPressRuntime => {
    const globalRef = globalThis as GlobalWithWP;
    const candidate = globalRef.wp?.element;

    if (candidate && typeof candidate === "object") {
        return candidate as WordPressRuntime;
    }

    throw new Error(
        "WordPress element runtime is unavailable. Ensure the wp-element script is enqueued before the Context Alt Text bundle.",
    );
};

const runtime = resolveWordPressElement();

export default runtime;
export const {
    Children,
    Component,
    Fragment,
    PureComponent,
    StrictMode,
    Suspense,
    cloneElement,
    concatChildren,
    createContext,
    createElement,
    createPortal,
    createRef,
    createRoot,
    findDOMNode,
    flushSync,
    forwardRef,
    hydrate,
    hydrateRoot,
    isValidElement,
    lazy,
    memo,
    render,
    startTransition,
    switchChildrenNodeName,
    unmountComponentAtNode,
    useCallback,
    useContext,
    useDebugValue,
    useDeferredValue,
    useEffect,
    useId,
    useImperativeHandle,
    useInsertionEffect,
    useLayoutEffect,
    useMemo,
    useReducer,
    useRef,
    useState,
    useSyncExternalStore,
    useTransition,
} = runtime;
