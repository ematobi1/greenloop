"use client";

import { useEffect } from "react";

// Calls `poll` now and every `intervalMs` while the tab is visible. A hidden tab stops
// polling; becoming visible again polls at once. `poll` should be stable (useCallback).
export function useVisiblePoll(poll: () => void, intervalMs: number): void {
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (timer !== null) return;
      poll();
      timer = setInterval(poll, intervalMs);
    };
    const stop = () => {
      if (timer !== null) clearInterval(timer);
      timer = null;
    };
    const onVisibility = () => (document.hidden ? stop() : start());
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [poll, intervalMs]);
}
