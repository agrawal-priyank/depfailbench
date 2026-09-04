# Contributing

Changes to documentation, packaging, provider adapters, and reporting are welcome. Experimental-protocol changes require additional care:

1. Open an issue describing the scientific reason for the change.
2. Update `protocol.json` and increment its version.
3. Add or update both handwritten controls.
4. Add deterministic tests before model generation.
5. Never modify frozen prompts, scenarios, or oracles after inspecting treatment results without labeling the new experiment as a separate protocol version.

Run `pytest -q` and `depfailbench validate-references --repetitions 3` before proposing a change. Do not commit provider keys, local `.env` files, or unpublished artifact data.
