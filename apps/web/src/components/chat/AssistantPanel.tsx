"use client";

import { useEffect, useRef } from "react";

import PlanPanel from "./PlanPanel";
import { canRemember, type ChatSession } from "./useChatSession";

const SUGGESTIONS = [
  "What do you remember about my current projects?",
  "Summarize what we talked about last time.",
  "Help me plan my week.",
  "What should I save to memory from today?",
];

// The open thread, Remember, Draft a plan, and the chat's status regions. Server text
// (messages, memory) is rendered as React text children, so it is escaped. Memory and
// model output are untrusted: never render them as HTML.
export default function AssistantPanel({ chat, onSuggest }: { chat: ChatSession; onSuggest: (text: string) => void }) {
  const { activeId, messages, hidden, streaming, remembered, followTick } = chat;
  const list = useRef<HTMLOListElement>(null);
  // Follow new messages only while the reader is at the bottom; scrolling up stops it.
  const following = useRef(true);

  useEffect(() => {
    following.current = true;
  }, [followTick]);

  useEffect(() => {
    const element = list.current;
    if (element && following.current) element.scrollTop = element.scrollHeight;
  }, [messages, streaming, followTick]);

  function onScroll() {
    const element = list.current;
    if (element) following.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48;
  }

  return (
    <section className="hud-panel chat__main" aria-labelledby="assistant-title">
      <h2 id="assistant-title" className="hud-panel__title">
        Assistant
      </h2>
      {activeId === null ? (
        <>
          <p className="chat__empty">Ask anything below, or try one of these:</p>
          <ul className="hud-suggestions">
            {SUGGESTIONS.map((text) => (
              <li key={text}>
                <button type="button" className="hud-suggestion" onClick={() => onSuggest(text)}>
                  {text}
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <>
          {hidden > 0 && <p className="chat__empty">{hidden} earlier messages aren&apos;t shown.</p>}
          <ol ref={list} className="chat__messages" onScroll={onScroll}>
            {messages.map((message, index) => (
              <li key={message.key} className={`message message--${message.role === "user" ? "user" : "assistant"}`}>
                <span className="message__role">{message.role === "user" ? "You" : "GreenLoop"}</span>
                <p className="message__text">{message.content}</p>
                {message.incomplete ? (
                  <span className="message__note">Reply incomplete</span>
                ) : !canRemember(messages, index) ? null : remembered.has(message.key) ? (
                  <span className="message__note">Saved to memory</span>
                ) : (
                  <button
                    type="button"
                    className="button button--quiet message__remember"
                    onClick={() => void chat.remember(message.key)}
                  >
                    Remember
                  </button>
                )}
              </li>
            ))}
            {streaming !== null && (
              <li className="message message--assistant message--streaming">
                <span className="message__role">GreenLoop</span>
                <p className="message__text">{streaming}</p>
              </li>
            )}
          </ol>
          <PlanPanel key={activeId} conversationId={activeId} onError={chat.handle} onDrafted={chat.changed} />
        </>
      )}
      <p className="visually-hidden" aria-live="polite" data-reply-announcement>
        {chat.announcement}
      </p>
      <p className="chat__error" role="alert">
        {chat.error}
      </p>
      <p className="chat__notice" role="status">
        {chat.statusNote}
      </p>
    </section>
  );
}
