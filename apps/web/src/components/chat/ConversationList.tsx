"use client";

import type { ChatSession } from "./useChatSession";

export default function ConversationList({ chat }: { chat: ChatSession }) {
  const { conversations, conversationTotal, activeId, streaming } = chat;
  return (
    <section className="hud-panel chat__sidebar" aria-labelledby="conversations-title">
      <h2 id="conversations-title" className="hud-panel__title">
        Conversations
      </h2>
      <button type="button" className="button" disabled={streaming !== null} onClick={() => void chat.newConversation()}>
        Start a conversation
      </button>
      <ul className="chat__conversations">
        {conversations.map((conversation) => (
          <li key={conversation.conversation_id}>
            <button
              type="button"
              className="chat__conversation"
              aria-current={conversation.conversation_id === activeId ? "true" : undefined}
              onClick={() => chat.select(conversation.conversation_id)}
            >
              {conversation.title}
            </button>
          </li>
        ))}
      </ul>
      {conversationTotal > conversations.length && (
        <p className="chat__empty">Showing your {conversations.length} most recent conversations.</p>
      )}
    </section>
  );
}
