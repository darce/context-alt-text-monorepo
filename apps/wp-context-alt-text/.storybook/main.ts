import type { StorybookConfig } from "@storybook/react-vite";
import { mergeConfig } from "vite";

const toFileSystemPath = (relative: string): string => {
  const url = new URL(relative, import.meta.url);
  const pathname = decodeURIComponent(url.pathname);

  if (/^\/[A-Za-z]:/.test(pathname)) {
    return pathname.slice(1);
  }

  return pathname;
};

const aliasRoot = toFileSystemPath("../js");

const config: StorybookConfig = {
  stories: ["../js/**/*.stories.@(ts|tsx|js|jsx)"],
  addons: [],
  framework: {
    name: "@storybook/react-vite",
    options: {},
  },
  viteFinal: (config) => {
    return mergeConfig(config, {
      resolve: {
        alias: {
          "@": aliasRoot,
        },
      },
    });
  },
};

export default config;
