import Element from "./wp-wordpress-element";

export const render = Element.render;
export const hydrate = Element.hydrate;
export const unmountComponentAtNode = Element.unmountComponentAtNode;
export const findDOMNode = Element.findDOMNode;
export const createPortal = Element.createPortal;
export const flushSync = Element.flushSync;
export const unstable_batchedUpdates: ((callback: () => void) => void) | undefined = undefined;
export const createRoot = Element.createRoot;
export const hydrateRoot = Element.hydrateRoot;

export default Element;

export type * from "react-dom";
