"use client";

import { useState, type FormEvent } from "react";

import * as api from "@/lib/api";

// Drafts a plan from this conversation. The plan is only a draft: nothing runs.
// Model output is untrusted, so steps render as text only.
export default function PlanPanel({
  conversationId,
  onError,
}: {
  conversationId: string;
  onError: (caught: unknown) => void;
}) {
  const [goal, setGoal] = useState("");
  const [pending, setPending] = useState(false);
  const [plan, setPlan] = useState<api.Plan | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || goal.trim() === "") return;
    setPending(true);
    try {
      setPlan(await api.draftPlan(goal.trim(), conversationId));
      setGoal("");
    } catch (caught) {
      onError(caught);
    } finally {
      setPending(false);
    }
  }

  async function discard() {
    if (!plan) return;
    try {
      await api.discardPlan(plan.plan_id);
      setPlan(null);
    } catch (caught) {
      onError(caught);
    }
  }

  return (
    <section className="plan" aria-label="Plan">
      <form className="memory__search" onSubmit={submit}>
        <label htmlFor="plan-goal" className="visually-hidden">
          Goal to plan
        </label>
        <input
          id="plan-goal"
          className="sign-in__input"
          maxLength={2000}
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          placeholder="Draft a plan for…"
        />
        <button type="submit" className="button button--quiet" disabled={pending || goal.trim() === ""}>
          {pending ? "Drafting…" : "Draft a plan"}
        </button>
      </form>
      {plan && (
        <article className="message plan__card" aria-label="Draft plan">
          <span className="message__role">Draft plan · nothing runs until you approve it</span>
          <p className="message__text">{plan.goal}</p>
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
          <div className="memory__actions">
            <button type="button" className="button button--quiet" onClick={() => void discard()}>
              Discard plan
            </button>
          </div>
        </article>
      )}
    </section>
  );
}
