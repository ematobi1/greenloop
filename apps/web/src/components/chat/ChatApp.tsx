"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import ActivityFeed from "@/components/hud/ActivityFeed";
import HealthPanel from "@/components/hud/HealthPanel";
import HudGlobe from "@/components/hud/HudGlobe";
import KpiRow from "@/components/hud/KpiRow";
import { useHudData } from "@/components/shell/HudData";
import * as api from "@/lib/api";
import { isSignedOut, messageFor, type ApiFailure } from "@/lib/errors";
import { nextCoreState, type ChatSignal, type CoreState } from "@/lib/globe";

import PlanPanel from "./PlanPanel";

type Shown = { key: string; role: string; content: string; incomplete: boolean };

const shown = (message: api.Message): Shown => ({
  key: message.message_id,
  role: message.role,
  content: message.content,
  incomplete: message.status !== "complete",
});

const SUGGESTIONS = [
  "What do you remember about my current projects?",
  "Summarize what we talked about last time.",
  "Help me plan my week.",
  "What should I save to memory from today?",
];

// The server's rule: a reply, or a user message that got a complete reply right after it.
function canRemember(messages: Shown[], index: number): boolean {
  const message = messages[index];
  if (message.role !== "user") return true;
  const reply = messages[index + 1];
  return reply !== undefined && reply.role !== "user" && !reply.incomplete;
}

// The HUD command center (ADR 0014): KPI tiles, conversations and live activity, the
// globe, the assistant panel and system health, and the Ask bar, which is the real chat.
// All text from the server (messages, titles, memory) is rendered as React text children,
// so it is escaped. Memory and model output are untrusted: never render them as HTML.
export default function ChatApp() {
  const router = useRouter();
  const { health, refresh } = useHudData();
  const [conversations, setConversations] = useState<api.Conversation[]>([]);
  const [conversationTotal, setConversationTotal] = useState(0);
  const [hidden, setHidden] = useState(0);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Shown[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusNote, setStatusNote] = useState<string | null>(null);
  const [remembered, setRemembered] = useState<ReadonlySet<string>>(new Set());
  const [coreState, setCoreState] = useState<CoreState>("idle");
  const [deltaTick, setDeltaTick] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const abort = useRef<AbortController | null>(null);
  const draftField = useRef<HTMLTextAreaElement>(null);

  const signal = useCallback((event: ChatSignal) => setCoreState((current) => nextCoreState(current, event)), []);
  const changed = useCallback(() => {
    setReloadKey((key) => key + 1);
    refresh();
  }, [refresh]);

  const fail = useCallback(
    (failure: ApiFailure) => {
      if (isSignedOut(failure)) {
        abort.current?.abort();
        router.replace(api.EXPIRED_SIGN_IN);
        return;
      }
      setError(messageFor(failure));
    },
    [router],
  );

  const handle = useCallback(
    (caught: unknown) => {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      fail(caught instanceof api.ApiError ? caught.failure : { status: 0, code: "UNEXPECTED", message: "" });
    },
    [fail],
  );

  const loadConversations = useCallback(() => {
    api.listConversations().then(({ conversations: rows, total }) => {
      setConversations(rows);
      setConversationTotal(total);
    }, handle);
  }, [handle]);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (!activeId) return;
    let current = true;
    api.listMessages(activeId).then(
      (page) => {
        if (!current) return;
        setMessages(page.messages.map(shown));
        setHidden(page.hidden);
      },
      (caught) => current && handle(caught),
    );
    return () => {
      current = false;
    };
  }, [activeId, handle]);

  useEffect(() => () => abort.current?.abort(), []);

  function select(conversationId: string) {
    if (streaming !== null) return;
    setError(null);
    setStatusNote(null);
    setMessages([]);
    setHidden(0);
    setActiveId(conversationId);
  }

  async function newConversation(): Promise<string | null> {
    setError(null);
    try {
      const created = await api.createConversation();
      setConversations((current) => [created, ...current]);
      setConversationTotal((total) => total + 1);
      select(created.conversation_id);
      changed();
      return created.conversation_id;
    } catch (caught) {
      handle(caught);
      return null;
    }
  }

  async function sendDraft() {
    const content = draft;
    if (streaming !== null || content.trim() === "") return;
    setError(null);
    const conversationId = activeId ?? (await newConversation());
    if (!conversationId) return;
    setStreaming("");
    signal("send");
    const controller = new AbortController();
    abort.current = controller;
    let failed = false;
    try {
      await api.streamMessage(
        conversationId,
        content,
        {
          onUserMessage: (message) => {
            setDraft((current) => (current === content ? "" : current));
            setMessages((current) => [...current, shown(message)]);
          },
          onDelta: (text) => {
            setStreaming((current) => (current ?? "") + text);
            setDeltaTick((tick) => tick + 1);
            signal("delta");
          },
          onDone: (message) => setMessages((current) => [...current, shown(message)]),
          onError: (failure, partial) => {
            failed = true;
            signal("error");
            if (partial) setMessages((current) => [...current, { ...shown(partial), incomplete: true }]);
            fail(failure);
          },
        },
        controller.signal,
      );
      if (!failed) signal("done");
    } catch (caught) {
      signal("error");
      handle(caught);
    } finally {
      setStreaming(null);
      abort.current = null;
      loadConversations();
      changed();
    }
  }

  async function remember(messageId: string) {
    if (!activeId) return;
    setError(null);
    setStatusNote(null);
    try {
      await api.rememberMessage(activeId, messageId);
      setRemembered((current) => new Set(current).add(messageId));
      setStatusNote("Saved to memory.");
      changed();
    } catch (caught) {
      if (caught instanceof api.ApiError && caught.failure.code === "ALREADY_REMEMBERED") {
        setRemembered((current) => new Set(current).add(messageId));
      }
      handle(caught);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendDraft();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void sendDraft();
    }
  }

  function suggest(text: string) {
    setDraft(text);
    draftField.current?.focus();
  }

  return (
    <div className="hud" data-core-state={coreState}>
      <h1 className="visually-hidden">GreenLoop command center</h1>
      <KpiRow />

      <div className="hud__grid">
        <div className="hud__left">
          <section className="hud-panel chat__sidebar" aria-labelledby="conversations-title">
            <h2 id="conversations-title" className="hud-panel__title">
              Conversations
            </h2>
            <button type="button" className="button" disabled={streaming !== null} onClick={() => void newConversation()}>
              Start a conversation
            </button>
            <ul className="chat__conversations">
              {conversations.map((conversation) => (
                <li key={conversation.conversation_id}>
                  <button
                    type="button"
                    className="chat__conversation"
                    aria-current={conversation.conversation_id === activeId ? "true" : undefined}
                    onClick={() => select(conversation.conversation_id)}
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
          <ActivityFeed conversations={conversations} reloadKey={reloadKey} onError={handle} />
        </div>

        <div className="hud__center hud-panel">
          <HudGlobe coreState={coreState} deltaTick={deltaTick} health={health} />
        </div>

        <div className="hud__right">
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
                      <button type="button" className="hud-suggestion" onClick={() => suggest(text)}>
                        {text}
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <>
                {hidden > 0 && <p className="chat__empty">{hidden} earlier messages aren&apos;t shown.</p>}
                <ol className="chat__messages">
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
                          onClick={() => void remember(message.key)}
                        >
                          Remember
                        </button>
                      )}
                    </li>
                  ))}
                  {streaming !== null && (
                    <li className="message message--assistant">
                      <span className="message__role">GreenLoop</span>
                      <p className="message__text" aria-live="polite" aria-busy="true">
                        {streaming}
                      </p>
                    </li>
                  )}
                </ol>
                <PlanPanel key={activeId} conversationId={activeId} onError={handle} onDrafted={changed} />
              </>
            )}
            <p className="chat__error" role="alert">
              {error}
            </p>
            <p className="chat__notice" role="status">
              {statusNote}
            </p>
          </section>
          <HealthPanel />
        </div>
      </div>

      <form className="hud-ask chat__composer" onSubmit={submit}>
        <label htmlFor="message-draft" className="visually-hidden">
          Message
        </label>
        <textarea
          ref={draftField}
          id="message-draft"
          className="chat__draft hud-ask__field"
          rows={1}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask GreenLoop… (Enter sends, Shift+Enter adds a line)"
        />
        <button type="submit" className="button hud-ask__send" disabled={streaming !== null || draft.trim() === ""}>
          {streaming !== null ? "Replying…" : "Send"}
        </button>
      </form>
    </div>
  );
}
