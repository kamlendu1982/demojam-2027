# Config directory

- `attribute_classification.yaml` — the single deterministic source of truth
  used by **Agent 1** to decide whether an incoming device attribute is a
  *security* setting (routed to Agent 3 / GitHub) or a *networking* setting
  (checked directly against NetBox). Extend this file whenever you introduce
  a new attribute name so the pipeline never needs to fall back to the LLM
  classifier.

No other files in this directory are required to run the demo. See the
project root `README.md` for the full architecture and setup instructions.
