"use client";

import { useState, type FormEvent } from "react";

import * as api from "@/lib/api";
import { messageFor } from "@/lib/errors";

// Token paste is a stand-in until real user login (ADR 0010). The field is a password
// input with autocomplete off; the token is sent once to /api/session and dropped.
export default function SignInForm({ notice, onSignedIn }: { notice: string | null; onSignedIn: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await api.signIn(token.trim());
      setToken("");
      onSignedIn();
    } catch (failure) {
      setError(failure instanceof api.ApiError ? messageFor(failure.failure) : messageFor({ status: 0, code: "", message: "" }));
    } finally {
      setPending(false);
    }
  }

  const message = error ?? notice;
  return (
    <form className="sign-in" onSubmit={submit} aria-labelledby="sign-in-title">
      <h1 id="sign-in-title" className="section__title">
        Sign in
      </h1>
      <label htmlFor="api-token" className="sign-in__label">
        GreenLoop API token
      </label>
      <input
        id="api-token"
        name="api-token"
        type="password"
        autoComplete="off"
        spellCheck={false}
        required
        className="sign-in__input"
        value={token}
        onChange={(event) => setToken(event.target.value)}
      />
      <button type="submit" className="button" disabled={pending || token.trim() === ""}>
        {pending ? "Signing in…" : "Sign in"}
      </button>
      <p className="sign-in__error" role="alert">
        {message}
      </p>
    </form>
  );
}
