import "@testing-library/jest-dom";

// Newer Node versions ship their own experimental global `localStorage`
// (gated behind `--localstorage-file`) as a getter/setter pair directly on
// `globalThis`. Because it's an accessor (not a plain value), Vitest's jsdom
// environment installing its own implementation via a plain assignment
// (`globalThis.localStorage = ...`) just invokes Node's setter instead of
// replacing the property -- so `window.localStorage` silently ends up
// `undefined` too (jsdom's `window` *is* `globalThis` here), and every
// `getItem`/`setItem` call is a no-op. Replace the accessor outright with a
// small in-memory Storage polyfill so tests get real, working storage
// regardless of Node version -- unless jsdom's own implementation already
// works, in which case leave it alone.
function installWorkingLocalStorage(): void {
  const existing = (globalThis as { localStorage?: Storage }).localStorage;
  if (existing) {
    try {
      existing.setItem("__setup_probe__", "1");
      const ok = existing.getItem("__setup_probe__") === "1";
      existing.removeItem("__setup_probe__");
      if (ok) return;
    } catch {
      // fall through to the polyfill below
    }
  }

  const store = new Map<string, string>();
  const polyfill: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key) => (store.has(key) ? store.get(key)! : null),
    key: (index) => Array.from(store.keys())[index] ?? null,
    removeItem: (key) => {
      store.delete(key);
    },
    setItem: (key, value) => {
      store.set(key, String(value));
    },
  };

  Object.defineProperty(globalThis, "localStorage", { value: polyfill, configurable: true, writable: true });
}

installWorkingLocalStorage();
