Additional resilience requirements:

Handle temporary dependency failures with bounded, task-appropriate retries where recovery is feasible. Use finite timeouts, and keep attempts plus any backoff or Retry-After wait within the remaining whole-request allowance. Propagate the remaining allowance to later dependency calls. Stop with an accurate HTTP error when recovery cannot fit; avoid retry storms and never exceed the declared attempt limit.

Validate successful downstream responses before claiming success. Preserve complete pagination without missing or duplicated records. For side-effecting actions, use the provider's documented idempotency support consistently across retries and preserve confirmed versus unknown outcomes. For idempotent writes, retry the same logical content and identity without altering the intended final state. Do not falsely report success or definite rejection after an ambiguous committed operation.
