"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Dismissed one-off UI, kept in localStorage alongside the other preferences.
 *
 * Deliberately separate from the favourites/recents store: those carry data the
 * user built up, this carries a single boolean per key, and mixing them would
 * make a schema bump to one invalidate the other.
 */
const KEY = "arbitrium:dismissed:v1";

const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function read(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function useJsonItemDismissed(id: string) {
  const raw = useSyncExternalStore(
    subscribe,
    () => read(),
    () => null,
  );
  const ready = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );

  let dismissed = false;
  if (raw) {
    try {
      dismissed = Boolean((JSON.parse(raw) as Record<string, boolean>)[id]);
    } catch {
      dismissed = false;
    }
  }

  const dismiss = useCallback(() => {
    let current: Record<string, boolean> = {};
    const existing = read();
    if (existing) {
      try {
        current = JSON.parse(existing) as Record<string, boolean>;
      } catch {
        current = {};
      }
    }
    try {
      window.localStorage.setItem(KEY, JSON.stringify({ ...current, [id]: true }));
    } catch {
      // Non-essential preference; failing to persist is not worth surfacing.
    }
    for (const l of listeners) l();
  }, [id]);

  return { dismissed, dismiss, ready };
}
