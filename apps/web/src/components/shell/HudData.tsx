"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import * as api from "@/lib/api";
import { isSignedOut } from "@/lib/errors";
import { REFRESH_MS, type Health, type Overview } from "@/lib/hud";

type HudData = { overview: Overview | null; health: Health | null; refresh: () => void };

const Context = createContext<HudData>({ overview: null, health: null, refresh: () => undefined });

export function useHudData(): HudData {
  return useContext(Context);
}

// Polls /api/overview and /api/health every REFRESH_MS while the tab is visible; a hidden
// tab stops polling, and becoming visible again refreshes at once.
export function HudDataProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [health, setHealth] = useState<Health | null>(null);

  const refresh = useCallback(() => {
    const onError = (caught: unknown) => {
      if (caught instanceof api.ApiError && isSignedOut(caught.failure)) router.replace(api.EXPIRED_SIGN_IN);
    };
    api.overview().then(setOverview, onError);
    api.health().then(setHealth, onError);
  }, [router]);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (timer !== null) return;
      refresh();
      timer = setInterval(refresh, REFRESH_MS);
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
  }, [refresh]);

  return <Context.Provider value={{ overview, health, refresh }}>{children}</Context.Provider>;
}
