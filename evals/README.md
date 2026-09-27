# Evals

The single home for prompt and injection evals. Security and behavior tests that run without a model stay in each service's `tests/security/`.

| Folder | Contents |
|---|---|
| `prompts/` | Prompt quality evals for system prompts and context framing |
| `injection/` | Prompt injection and memory-poisoning evals |
| `datasets/` | Eval inputs and expected outputs |

Evals call a model, so they are slower and paid. They run before release and on a schedule, each with a pass threshold. No evals run during scaffolding.
