"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import * as api from "@/lib/api";
import { isSignedOut, messageFor } from "@/lib/errors";

// Shows the real signed-in username from /api/session; a 401 means the session ended.
export default function UserMenu() {
  const router = useRouter();
  const [username, setUsername] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    api.currentSession().then(
      (session) => setUsername(session.username),
      (caught) => {
        if (caught instanceof api.ApiError && isSignedOut(caught.failure)) router.replace(api.EXPIRED_SIGN_IN);
      },
    );
  }, [router]);

  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open]);

  async function signOut(everywhere: boolean) {
    setError(null);
    try {
      await api.signOut(everywhere);
    } catch (caught) {
      if (caught instanceof api.ApiError && !isSignedOut(caught.failure)) {
        setError(messageFor(caught.failure));
        return;
      }
    }
    router.replace("/sign-in");
    router.refresh();
  }

  return (
    <div className="hud-user">
      <button
        ref={button}
        type="button"
        className="button button--quiet hud-user__button"
        aria-expanded={open}
        aria-controls="user-menu"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="visually-hidden">Signed in as </span>
        <span className="hud-user__name">{username ?? "…"}</span>
      </button>
      {open && (
        <div id="user-menu" className="hud-user__menu hud-panel">
          <button type="button" className="button button--quiet" onClick={() => void signOut(false)}>
            Sign out
          </button>
          <button type="button" className="button button--quiet" onClick={() => void signOut(true)}>
            Sign out everywhere
          </button>
          <p className="chat__error" role="alert">
            {error}
          </p>
        </div>
      )}
    </div>
  );
}
