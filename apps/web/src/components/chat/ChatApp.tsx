"use client";

import { useRef } from "react";

import ActivityFeed from "@/components/hud/ActivityFeed";
import HealthPanel from "@/components/hud/HealthPanel";
import HudGlobe from "@/components/hud/HudGlobe";
import KpiRow from "@/components/hud/KpiRow";
import { useHudData } from "@/components/shell/HudData";

import AskBar from "./AskBar";
import AssistantPanel from "./AssistantPanel";
import ConversationList from "./ConversationList";
import { useChatSession } from "./useChatSession";

// The HUD command center (ADR 0014): KPI tiles, conversations and live activity, the
// globe, the assistant panel and system health, and the Ask bar, which is the real chat.
// The chat's state lives in useChatSession; this component is only the layout.
export default function ChatApp() {
  const { health } = useHudData();
  const chat = useChatSession();
  const draftField = useRef<HTMLTextAreaElement>(null);

  function suggest(text: string) {
    chat.setDraft(text);
    draftField.current?.focus();
  }

  return (
    <div className="hud" data-core-state={chat.coreState}>
      <h1 className="visually-hidden">GreenLoop command center</h1>
      <KpiRow />

      <div className="hud__grid">
        <div className="hud__left">
          <ConversationList chat={chat} />
          <ActivityFeed conversations={chat.conversations} reloadKey={chat.reloadKey} />
        </div>

        <div className="hud__center hud-panel">
          <HudGlobe coreState={chat.coreState} deltaTick={chat.deltaTick} health={health} />
        </div>

        <div className="hud__right">
          <AssistantPanel chat={chat} onSuggest={suggest} />
          <HealthPanel />
        </div>
      </div>

      <AskBar chat={chat} field={draftField} />
    </div>
  );
}
