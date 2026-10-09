"use client";

import type { FormEvent, KeyboardEvent, RefObject } from "react";

import type { ChatSession } from "./useChatSession";

// The bottom "Ask GreenLoop…" bar: Enter sends, Shift+Enter adds a line.
export default function AskBar({ chat, field }: { chat: ChatSession; field: RefObject<HTMLTextAreaElement | null> }) {
  const { draft, streaming } = chat;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void chat.sendDraft();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void chat.sendDraft();
    }
  }

  return (
    <form className="hud-ask chat__composer" onSubmit={submit}>
      <label htmlFor="message-draft" className="visually-hidden">
        Message
      </label>
      <textarea
        ref={field}
        id="message-draft"
        className="chat__draft hud-ask__field"
        rows={1}
        value={draft}
        onChange={(event) => chat.setDraft(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask GreenLoop… (Enter sends, Shift+Enter adds a line)"
      />
      <button type="submit" className="button hud-ask__send" disabled={streaming !== null || draft.trim() === ""}>
        {streaming !== null ? "Replying…" : "Send"}
      </button>
    </form>
  );
}
