"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import * as api from "@/lib/api";
import { isSignedOut, messageFor } from "@/lib/errors";

// Plans GreenLoop drafted. Drafts only: nothing runs until approval arrives (Phase 4).
// Model output is untrusted, so goals and steps render as text only.
export default function PlansApp() {
  const router = useRouter();
  const [plans, setPlans] = useState<api.Plan[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const handle = useCallback(
    (caught: unknown) => {
      if (caught instanceof api.ApiError && isSignedOut(caught.failure)) {
        router.replace(api.EXPIRED_SIGN_IN);
        return;
      }
      setError(messageFor(caught instanceof api.ApiError ? caught.failure : { status: 0, code: "", message: "" }));
    },
    [router],
  );

  const load = useCallback(() => {
    api.listPlans().then(setPlans, handle);
  }, [handle]);

  useEffect(() => {
    load();
  }, [load]);

  async function discard(planId: string) {
    setError(null);
    try {
      await api.discardPlan(planId);
      setStatus("Plan discarded.");
      load();
    } catch (caught) {
      handle(caught);
    }
  }

  return (
    <section className="hud-panel plans" aria-labelledby="plans-title">
      <h1 id="plans-title" className="section__title">
        Plans
      </h1>
      <p className="section__summary">Drafts GreenLoop wrote for you. Nothing runs until you approve it, from Phase 4.</p>
      {plans === null ? (
        <p className="chat__empty">Loading…</p>
      ) : plans.length === 0 ? (
        <p className="chat__empty">No plans yet. Use “Draft a plan” in a conversation.</p>
      ) : (
        <ul className="plans__list">
          {plans.map((plan) => (
            <li key={plan.plan_id} className="message plans__item" data-status={plan.status}>
              <span className="hud-label">
                {plan.status === "draft" ? "Draft" : "Discarded"} · {new Date(plan.created_at).toLocaleString()}
              </span>
              <p className="plan__title">{plan.goal}</p>
              <ol className="plan__steps">
                {plan.steps.map((step, index) => (
                  <li key={index}>
                    <p className="plan__title">{step.title}</p>
                    {step.description && <p className="message__text">{step.description}</p>}
                    {step.depends_on.length > 0 && (
                      <p className="message__note">After step {step.depends_on.map((n) => n + 1).join(", ")}</p>
                    )}
                  </li>
                ))}
              </ol>
              {plan.status === "draft" && (
                <div className="memory__actions">
                  <button type="button" className="button button--quiet" onClick={() => void discard(plan.plan_id)}>
                    Discard plan
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="chat__error" role="alert">
        {error}
      </p>
      <p className="chat__notice" role="status">
        {status}
      </p>
    </section>
  );
}
