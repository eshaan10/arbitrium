import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * False during SSR and the hydration pass, true afterwards.
 *
 * For values that legitimately differ between server and browser — a locale
 * timestamp, anything derived from `Date.now()` — this is the lint-clean way to
 * defer them to the client without a setState-in-effect.
 */
export function useIsClient(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
