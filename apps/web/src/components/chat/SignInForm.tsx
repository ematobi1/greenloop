"use client";

import { useState, type FormEvent } from "react";

import * as api from "@/lib/api";
import { messageFor } from "@/lib/errors";

// Username and password go to /api/session once; the browser keeps neither (ADR 0012).
export default function SignInForm({ notice, onSignedIn }: { notice: string | null; onSignedIn: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await api.signIn(username.trim(), password);
      setPassword("");
      onSignedIn();
    } catch (failure) {
      setPassword("");
      setError(messageFor(failure instanceof api.ApiError ? failure.failure : { status: 0, code: "", message: "" }));
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
      <label htmlFor="username" className="sign-in__label">
        Username
      </label>
      <input
        id="username"
        name="username"
        type="text"
        autoComplete="username"
        autoCapitalize="none"
        spellCheck={false}
        required
        className="sign-in__input"
        value={username}
        onChange={(event) => setUsername(event.target.value)}
      />
      <label htmlFor="password" className="sign-in__label">
        Password
      </label>
      <input
        id="password"
        name="password"
        type="password"
        autoComplete="current-password"
        required
        className="sign-in__input"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <button type="submit" className="button" disabled={pending || username.trim() === "" || password === ""}>
        {pending ? "Signing in…" : "Sign in"}
      </button>
      <p className="sign-in__error" role="alert">
        {message}
      </p>
    </form>
  );
}
