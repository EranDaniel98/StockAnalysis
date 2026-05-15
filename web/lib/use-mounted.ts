"use client";

import { useEffect, useState } from "react";

/**
 * Returns `true` after the component has mounted on the client.
 *
 * Use to gate values that legitimately differ between server-render and
 * the first client paint — e.g. TanStack Query's `isFetching`, which is
 * `false` during SSR (no fetch in flight) but flips to `true` the moment
 * `useQuery` mounts on the client, producing a `disabled={false}` →
 * `disabled={true}` hydration mismatch on Refresh buttons. Gating the
 * disabled prop with `mounted ? isFetching : false` makes the SSR
 * markup match the first client render, and then React patches in the
 * real value on the next render — no warning.
 */
export function useMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  return mounted;
}
