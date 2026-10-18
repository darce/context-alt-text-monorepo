/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CLERK_PUBLISHABLE_KEY?: string;
  readonly VITE_CLERK_FAPI?: string;
  readonly VITE_PORTAL_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
