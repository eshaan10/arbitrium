"use client";

import { useEffect } from "react";
import { migrateLegacyFavorites } from "@/lib/storage";

/**
 * Runs one-time localStorage migrations on the client, then renders nothing.
 *
 * An effect writing to an external store is exactly what effects are for, and
 * localStorage is only reachable in the browser anyway. The migration itself is
 * self-idempotent — it removes the key it reads — so mounting this more than
 * once is harmless.
 */
export function StorageMigrations() {
  useEffect(() => {
    migrateLegacyFavorites();
  }, []);

  return null;
}
