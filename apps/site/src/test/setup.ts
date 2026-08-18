import "@testing-library/jest-dom/vitest";

const values = new Map<string, string>();
const localStorageMock: Storage = {
  get length() { return values.size; },
  clear: () => values.clear(),
  getItem: (key) => values.get(key) ?? null,
  key: (index) => [...values.keys()][index] ?? null,
  removeItem: (key) => { values.delete(key); },
  setItem: (key, value) => { values.set(key, String(value)); },
};

Object.defineProperty(window, "localStorage", { configurable: true, value: localStorageMock });
Object.defineProperty(globalThis, "localStorage", { configurable: true, value: localStorageMock });
Object.defineProperty(globalThis, "requestAnimationFrame", { configurable: true, value: (callback: FrameRequestCallback) => window.setTimeout(() => callback(performance.now()), 0) });
Object.defineProperty(globalThis, "cancelAnimationFrame", { configurable: true, value: (handle: number) => window.clearTimeout(handle) });

Object.defineProperty(window, "matchMedia", {
  configurable: true,
  value: (query: string) => ({
    matches: query.includes("prefers-reduced-motion"),
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});
