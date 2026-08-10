/**
 * The entry point. Everything interesting is in `App`; this file exists to mount
 * it and to fail loudly if the host page lost its root element.
 *
 * DECISION: no `StrictMode`. The panel's mount is not idempotent — Telegram's
 * launch string is single-use, and while `useSession` guards the double-mount
 * with a ref, running the whole tree twice in development only obscures the
 * ordering bugs that matter in a webview. The double-mount guard stays as
 * defence; the deliberate double render does not.
 */
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./index.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html is missing #root");
}

createRoot(root).render(<App />);
