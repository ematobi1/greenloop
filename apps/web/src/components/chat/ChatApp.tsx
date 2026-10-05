"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import * as api from "@/lib/api";
import { isSignedOut, messageFor, type ApiFailure } from "@/lib/errors";

import SignInForm from "./SignInForm";

type Shown = { key: string; role: string; content: string; incomplete: boolean };

const shown = (message: api.Message): Shown => ({
  key: message.message_id,
  role: message.role,
  content: message.content,
  incomplete: message.status !== "complete",
});

// All text from the server (messages, titles) is rendered as React text children, so
// it is escaped. Memory and model output are untrusted: never render them as HTML.
export default function ChatApp({ initiallySignedIn }: { initiallySignedIn: boolean }) {
  const [signedIn, setSignedIn] = useState(initiallySignedIn);
  const [notice, setNotice] = useState<string | null>(null);
  const [conversations, setConversations] = useState<api.Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Shown[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const fail = useCallback((failure: ApiFailure) => {
    if (isSignedOut(failure)) {
      abort.current?.abort();
      setSignedIn(false);
      setNotice(messageFor(failure));
      setConversations([]);
      setActiveId(null);
      setMessages([]);
      return;
    }
    setError(messageFor(failure));
  }, []);

  const handle = useCallback(
    (caught: unknown) => {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      fail(caught instanceof api.ApiError ? caught.failure : { status: 0, code: "UNEXPECTED", message: "" });
    },
    [fail],
  );

  useEffect(() => {
    if (!signedIn) return;
    api.listConversations().then(setConversations, handle);
  }, [signedIn, handle]);

  useEffect(() => {
    if (!activeId) return;
    let current = true;
    api.listMessages(activeId).then((rows) => current && setMessages(rows.map(shown)), handle);
    return () => {
      current = false;
    };
  }, [activeId, handle]);

  function select(conversationId: string) {
    if (streaming !== null) return;
    setError(null);
    setMessages([]);
    setActiveId(conversationId);
  }

  useEffect(() => () => abort.current?.abort(), []);

  async function newConversation() {
    setError(null);
    try {
      const created = await api.createConversation();
      setConversations((current) => [created, ...current]);
      select(created.conversation_id);
    } catch (caught) {
      handle(caught);
    }
  }

  async function sendDraft() {
    const content = draft;
    if (!activeId || streaming !== null || content.trim() === "") return;
    setError(null);
    setStreaming("");
    const controller = new AbortController();
    abort.current = controller;
    try {
      await api.streamMessage(
        activeId,
        content,
        {
          onUserMessage: (message) => {
            setDraft("");
            setMessages((current) => [...current, shown(message)]);
          },
          onDelta: (text) => setStreaming((current) => (current ?? "") + text),
          onDone: (message) => setMessages((current) => [...current, shown(message)]),
          onError: (failure, partial) => {
            if (partial) setMessages((current) => [...current, { ...shown(partial), incomplete: true }]);
            fail(failure);
          },
        },
        controller.signal,
      );
    } catch (caught) {
      handle(caught);
    } finally {
      setStreaming(null);
      abort.current = null;
    }
  }

  async function signOut() {
    abort.current?.abort();
    try {
      await api.signOut();
    } catch (caught) {
      handle(caught);
      return;
    }
    fail({ status: 401, code: "SIGNED_OUT_BY_USER", message: "" });
    setNotice("You're signed out.");
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

  if (!signedIn) {
    return (
      <SignInForm
        notice={notice}
        onSignedIn={() => {
          setNotice(null);
          setError(null);
          setSignedIn(true);
        }}
      />
    );
  }

  return (
    <div className="chat">
      <aside className="chat__sidebar" aria-label="Conversations">
        <button type="button" className="button" onClick={() => void newConversation()}>
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
        <button type="button" className="button button--quiet" onClick={() => void signOut()}>
          Sign out
        </button>
      </aside>

      <section className="chat__main" aria-label="Messages">
        {activeId === null ? (
          <p className="chat__empty">Pick a conversation or start a new one.</p>
        ) : (
          <>
            <ol className="chat__messages">
              {messages.map((message) => (
                <li key={message.key} className={`message message--${message.role === "user" ? "user" : "assistant"}`}>
                  <span className="message__role">{message.role === "user" ? "You" : "GreenLoop"}</span>
                  <p className="message__text">{message.content}</p>
                  {message.incomplete && <span className="message__note">Reply incomplete</span>}
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
            <form className="chat__composer" onSubmit={submit}>
              <label htmlFor="message-draft" className="visually-hidden">
                Message
              </label>
              <textarea
                id="message-draft"
                className="chat__draft"
                rows={3}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Write a message. Enter sends, Shift+Enter adds a line."
              />
              <button type="submit" className="button" disabled={streaming !== null || draft.trim() === ""}>
                {streaming !== null ? "Replying…" : "Send"}
              </button>
            </form>
          </>
        )}
        <p className="chat__error" role="alert">
          {error}
        </p>
      </section>
    </div>
  );
}
