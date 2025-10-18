declare module "@wordpress/element/build-module/react" {
    import * as ReactNamespace from "react";

    export const concatChildren: (...children: ReactNamespace.ReactNode[]) => ReactNamespace.ReactNode[];

    export const switchChildrenNodeName: (
        children: ReactNamespace.ReactNode,
        nodeName: string,
    ) => ReactNamespace.ReactNode;

    export * from "react";
    const ReactDefault: typeof ReactNamespace;
    export default ReactDefault;
}

declare module "@wordpress/element/build-module/react-platform" {
    import type * as ReactDOMNamespace from "react-dom";
    import type * as ReactDOMClientNamespace from "react-dom/client";

    export * from "react-dom";
    export * from "react-dom/client";

    const ReactPlatform: typeof ReactDOMNamespace & typeof ReactDOMClientNamespace;
    export default ReactPlatform;
}
