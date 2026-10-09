"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useHudData } from "@/components/shell/HudData";
import * as api from "@/lib/api";
import { isSignedOut, messageFor, type ApiFailure } from "@/lib/errors";
import { nextCoreState, type ChatSignal, type CoreState } from "@/lib/globe";

export type Shown = { key: string; role: string; content: string; incomplete: boolean };

const shown = (message: api.Message): Shown => ({
  key: message.message_id,
  role: message.role,
  content: message.content,
  incomplete: message.status !== "complete",
});

// The server's rule: a reply, or a user message that got a complete reply right after it.
export function canRemember(messages: Shown[], index: number): boolean {
  const message = messages[index];
  if (message.role !== "user") return true;
  const reply = messages[index + 1];
  return reply !== undefined && reply.role !== "user" && !reply.incomplete;
}

// All of the chat's state and actions: conversations, the open thread, the streamed reply,
// Remember, and what the globe shows (coreState, deltaTick). The HUD's panels only render it.
export function useChatSession() {
  const router = useRouter();
  const { refresh } = useHudData();
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
  // The finished reply, put in a persistent live region so screen readers announce it once.
  const [announcement, setAnnouncement] = useState("");
  const abort = useRef<AbortController | null>(null);
  // Bumped when a send starts, so a history load still in flight can't overwrite the
  // messages that the stream is adding.
  const loadSeq = useRef(0);
  // True while a reply streams: a history load that lands meanwhile (a brand-new
  // conversation's, say) must not replace the messages the stream is adding.
  const sending = useRef(false);
  // Set when a history load replaces the thread or a send starts: the thread jumps to the newest message.
  const [followTick, setFollowTick] = useState(0);

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
    const seq = ++loadSeq.current;
    api.listMessages(activeId).then(
      (page) => {
        if (!current || seq !== loadSeq.current || sending.current) return;
        setFollowTick((tick) => tick + 1);
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
    loadSeq.current += 1;
    sending.current = true;
    setFollowTick((tick) => tick + 1);
    setAnnouncement("");
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
          onDone: (message) => {
            setMessages((current) => [...current, shown(message)]);
            setAnnouncement(`GreenLoop replied: ${message.content}`);
          },
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
      sending.current = false;
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

  return {
    conversations,
    conversationTotal,
    hidden,
    activeId,
    messages,
    draft,
    setDraft,
    streaming,
    error,
    statusNote,
    remembered,
    coreState,
    deltaTick,
    reloadKey,
    announcement,
    followTick,
    handle,
    changed,
    select,
    newConversation,
    sendDraft,
    remember,
  };
}

export type ChatSession = ReturnType<typeof useChatSession>;
