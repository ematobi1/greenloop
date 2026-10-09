"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useHudData } from "@/components/shell/HudData";
import * as api from "@/lib/api";
import { isSignedOut } from "@/lib/errors";
import { activityItems } from "@/lib/hud";

// Live activity: recent conversations, memories and plans. The audit feed joins in Phase 3.
// It reloads on the shell's 30-second refresh (no timer of its own) and at once when the
// chat changes something. A failed reload keeps the last list and says so quietly here,
// never in the chat's alert.
export default function ActivityFeed({ conversations, reloadKey }: { conversations: api.Conversation[]; reloadKey: number }) {
  const router = useRouter();
  const { overview } = useHudData();
  const [memories, setMemories] = useState<api.MemoryRecord[]>([]);
  const [plans, setPlans] = useState<api.Plan[]>([]);
  const [stale, setStale] = useState(false);

  const load = useCallback(() => {
    const failed = (caught: unknown) => {
      if (caught instanceof api.ApiError && isSignedOut(caught.failure)) router.replace(api.EXPIRED_SIGN_IN);
      else setStale(true);
    };
    Promise.all([api.listMemory(), api.listPlans()]).then(([page, rows]) => {
      setMemories(page.records);
      setPlans(rows);
      setStale(false);
    }, failed);
  }, [router]);

  useEffect(() => {
    load();
  }, [overview, reloadKey, load]);

  const items = activityItems(conversations, memories, plans);
  return (
    <section className="hud-panel hud-activity" aria-labelledby="activity-title">
      <h2 id="activity-title" className="hud-panel__title">
        Live activity
      </h2>
      {items.length === 0 ? (
        <p className="chat__empty">Nothing yet. Start a conversation below.</p>
      ) : (
        <ol className="hud-activity__list">
          {items.map((item) => (
            <li key={`${item.kind}-${item.id}`} className={`hud-activity__item hud-activity__item--${item.kind}`}>
              <time dateTime={item.at}>{new Date(item.at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</time>
              <span>{item.text}</span>
            </li>
          ))}
        </ol>
      )}
      <p className="hud-updated">{stale ? "Couldn't refresh just now; showing the last list." : "Audit events arrive in Phase 3."}</p>
    </section>
  );
}
