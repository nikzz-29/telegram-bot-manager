/// <reference types="vite/client" />

/** `?raw` imports — the `.ftl` catalogues are pulled in as strings. */
declare module "*.ftl?raw" {
  const content: string;
  export default content;
}
