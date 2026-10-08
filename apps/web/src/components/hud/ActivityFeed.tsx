"use client";

import { useCallback, useEffect, useState } from "react";

import * as api from "@/lib/api";
import { REFRESH_MS, activityItems } from "@/lib/hud";
import { useVisiblePoll } from "@/lib/use-visible-poll";

// Live activity: recent conversations, memories and plans. The audit feed joins in Phase 3.
export default function ActivityFeed({
  conversations,
  reloadKey,
  onError,
}: {
  conversations: api.Conversation[];
  reloadKey: number;
  onError: (caught: unknown) => void;
}) {
  const [memories, setMemories] = useState<api.MemoryRecord[]>([]);
  const [plans, setPlans] = useState<api.Plan[]>([]);

  const load = useCallback(() => {
    api.listMemory().then((page) => setMemories(page.records), onError);
    api.listPlans().then(setPlans, onError);
  }, [onError]);
  useVisiblePoll(load, REFRESH_MS);

  // A finished reply, a remembered message or a new plan reloads at once.
  useEffect(() => {
    if (reloadKey > 0) load();
  }, [reloadKey, load]);

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
      <p className="hud-updated">Audit events arrive in Phase 3.</p>
    </section>
  );
}
