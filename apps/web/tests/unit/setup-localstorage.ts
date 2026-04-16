// Node 22+ ships a built-in localStorage that shadows jsdom's implementation
// when the "jsdom" test environment is used. The built-in is a plain object
// whose prototype is not Storage, so Storage.prototype methods (and spies
// against them) never fire.
//
// This setup file rewires Storage.prototype to use a WeakMap-backed store and
// installs a fresh instance at window.localStorage before each test, which
// restores the semantics that unit tests expect.

import { beforeEach } from "vitest";

const storeMap = new WeakMap<Storage, Map<string, string>>();

if (!Object.getOwnPropertyDescriptor(Storage.prototype, "__mraiInstalled")) {
  Object.defineProperty(Storage.prototype, "__mraiInstalled", {
    value: true,
    configurable: false,
    enumerable: false,
    writable: false,
  });
  Object.defineProperty(Storage.prototype, "getItem", {
    value(this: Storage, key: string): string | null {
      const m = storeMap.get(this);
      return m && m.has(key) ? m.get(key)! : null;
    },
    writable: true,
    configurable: true,
  });
  Object.defineProperty(Storage.prototype, "setItem", {
    value(this: Storage, key: string, value: string): void {
      const m = storeMap.get(this);
      if (!m) return;
      m.set(key, String(value));
    },
    writable: true,
    configurable: true,
  });
  Object.defineProperty(Storage.prototype, "removeItem", {
    value(this: Storage, key: string): void {
      storeMap.get(this)?.delete(key);
    },
    writable: true,
    configurable: true,
  });
  Object.defineProperty(Storage.prototype, "clear", {
    value(this: Storage): void {
      storeMap.get(this)?.clear();
    },
    writable: true,
    configurable: true,
  });
  Object.defineProperty(Storage.prototype, "key", {
    value(this: Storage, n: number): string | null {
      return [...(storeMap.get(this)?.keys() ?? [])][n] ?? null;
    },
    writable: true,
    configurable: true,
  });
  Object.defineProperty(Storage.prototype, "length", {
    get(this: Storage): number {
      return storeMap.get(this)?.size ?? 0;
    },
    configurable: true,
  });
}

function freshStorage(): Storage {
  const instance = Object.create(Storage.prototype) as Storage;
  storeMap.set(instance, new Map());
  return instance;
}

beforeEach(() => {
  Object.defineProperty(window, "localStorage", {
    value: freshStorage(),
    writable: true,
    configurable: true,
  });
  Object.defineProperty(window, "sessionStorage", {
    value: freshStorage(),
    writable: true,
    configurable: true,
  });
});
