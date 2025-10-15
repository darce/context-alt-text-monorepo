import Element from "./wp-wordpress-element";

export const createRoot = Element.createRoot;
export const hydrateRoot = Element.hydrateRoot;

export default {
    createRoot,
    hydrateRoot,
};

export type * from "react-dom/client";
