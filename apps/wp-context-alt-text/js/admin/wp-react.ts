import WordPressElement from "./wp-wordpress-element";

const Element = WordPressElement;

const elementRecord = Element as Record<string, unknown>;
const detectedVersion = typeof elementRecord.version === "string"
	? elementRecord.version
	: "18.2.0";

const react = {
	...Element,
	version: detectedVersion,
} as typeof Element & {
	version: string;
};

const {
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
} = Element;

export {
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
};

export const version = detectedVersion;

export type {
	ComponentProps,
	ComponentType,
	Context,
	Dispatch,
	EffectCallback,
	FC,
	ForwardRefExoticComponent,
	JSX,
	LazyExoticComponent,
	MutableRefObject,
	PropsWithChildren,
	ReactElement,
	ReactNode,
	Ref,
	RefObject,
} from "react";

export default react;
