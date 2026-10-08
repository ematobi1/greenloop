"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { useRouter } from "next/navigation";

import * as api from "@/lib/api";
import { isSignedOut, messageFor, type ApiFailure } from "@/lib/errors";

type Edit = { recordId: string; operation: "correct" | "supersede"; content: string };

const LABELS: Record<string, string> = {
  correct: "Correct",
  supersede: "Replace",
};

// Memory content is untrusted text: it is only ever rendered as React text children.
export default function MemoryApp() {
  const router = useRouter();
  const [records, setRecords] = useState<api.MemoryRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [history, setHistory] = useState<{ recordId: string; versions: api.MemoryRecord[] } | null>(null);
  const [edit, setEdit] = useState<Edit | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  const handle = useCallback((caught: unknown) => {
    const failure: ApiFailure =
      caught instanceof api.ApiError ? caught.failure : { status: 0, code: "UNEXPECTED", message: "" };
    if (isSignedOut(failure)) {
      router.replace(api.EXPIRED_SIGN_IN);
      return;
    }
    setError(messageFor(failure));
  }, [router]);

  useEffect(() => {
    let current = true;
    api.listMemory(search).then(
      (page) => {
        if (!current) return;
        setRecords(page.records);
        setTotal(page.total);
      },
      (caught) => current && handle(caught),
    );
    return () => {
      current = false;
    };
  }, [search, reload, handle]);

  function refresh(message: string) {
    setEdit(null);
    setHistory(null);
    setConfirmDelete(null);
    setStatus(message);
    setReload((count) => count + 1);
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setStatus(null);
    setSearch(query);
  }

  async function showHistory(recordId: string) {
    setError(null);
    if (history?.recordId === recordId) return setHistory(null);
    try {
      setHistory({ recordId, versions: await api.memoryHistory(recordId) });
    } catch (caught) {
      handle(caught);
    }
  }

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!edit || edit.content.trim() === "") return;
    setError(null);
    try {
      await api.reviseMemory(edit.recordId, edit.operation, edit.content);
      refresh(edit.operation === "correct" ? "Memory corrected." : "Memory replaced.");
    } catch (caught) {
      handle(caught);
    }
  }

  async function remove(recordId: string) {
    setError(null);
    try {
      await api.deleteMemory(recordId);
      refresh("Memory deleted. It won't be used in chat again.");
    } catch (caught) {
      handle(caught);
    }
  }

  return (
    <section className="memory hud-panel" aria-labelledby="memory-title">
      <h1 id="memory-title" className="section__title">
        Memory
      </h1>
      <form className="memory__search" role="search" onSubmit={submitSearch}>
        <label htmlFor="memory-search" className="visually-hidden">
          Search memory
        </label>
        <input
          id="memory-search"
          type="search"
          className="sign-in__input"
          maxLength={200}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search memory"
        />
        <button type="submit" className="button">
          Search
        </button>
      </form>
      <p className="chat__empty">
        {total === 0
          ? search
            ? "Nothing matches that search."
            : "Nothing saved yet. Use Remember in chat to save a message."
          : `${total} ${total === 1 ? "memory" : "memories"}${total > records.length ? `, showing the newest ${records.length}` : ""}.`}
      </p>
      <ul className="memory__list">
        {records.map((record) => (
          <li key={record.record_id} className="message memory__item">
            <p className="message__text">{record.content}</p>
            <p className="message__note">
              {record.category.replaceAll("_", " ")} · {record.confidence} · {record.provenance.source} ·{" "}
              {new Date(record.created_at).toLocaleString()}
            </p>
            {edit?.recordId === record.record_id ? (
              <form className="chat__composer" onSubmit={saveEdit}>
                <label htmlFor={`edit-${record.record_id}`} className="visually-hidden">
                  {LABELS[edit.operation]} memory
                </label>
                <textarea
                  id={`edit-${record.record_id}`}
                  className="chat__draft"
                  rows={3}
                  maxLength={20000}
                  value={edit.content}
                  onChange={(event) => setEdit({ ...edit, content: event.target.value })}
                />
                <div className="memory__actions">
                  <button type="submit" className="button" disabled={edit.content.trim() === ""}>
                    Save {LABELS[edit.operation].toLowerCase()}
                  </button>
                  <button type="button" className="button button--quiet" onClick={() => setEdit(null)}>
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <div className="memory__actions">
                <button type="button" className="button button--quiet" onClick={() => void showHistory(record.record_id)}>
                  {history?.recordId === record.record_id ? "Hide history" : "History"}
                </button>
                <button
                  type="button"
                  className="button button--quiet"
                  onClick={() => setEdit({ recordId: record.record_id, operation: "correct", content: record.content })}
                >
                  Correct
                </button>
                <button
                  type="button"
                  className="button button--quiet"
                  onClick={() => setEdit({ recordId: record.record_id, operation: "supersede", content: record.content })}
                >
                  Replace
                </button>
                {confirmDelete === record.record_id ? (
                  <>
                    <button type="button" className="button" onClick={() => void remove(record.record_id)}>
                      Confirm delete
                    </button>
                    <button type="button" className="button button--quiet" onClick={() => setConfirmDelete(null)}>
                      Keep
                    </button>
                  </>
                ) : (
                  <button type="button" className="button button--quiet" onClick={() => setConfirmDelete(record.record_id)}>
                    Delete
                  </button>
                )}
              </div>
            )}
            {history?.recordId === record.record_id && (
              <ol className="memory__history" aria-label="Versions, oldest first">
                {history.versions.map((version) => (
                  <li key={version.record_id}>
                    <span className="message__note">
                      {version.provenance.operation} · {new Date(version.created_at).toLocaleString()}
                    </span>
                    <p className="message__text">{version.content}</p>
                  </li>
                ))}
              </ol>
            )}
          </li>
        ))}
      </ul>
      <p className="chat__error" role="alert">
        {error}
      </p>
      <p className="chat__notice" role="status">
        {status}
      </p>
    </section>
  );
}
