# Extending the fault model without altering the frozen study

The historical four-task study remains fixed for exact replay. Version 1.1.0 adds a manifest-backed adapter interface for new tasks; see [Adding a task](ADDING_TASKS.md) and the runnable `examples/external_task` demonstration. The custom transport below remains a smaller illustration of dependency scripting.

The runnable `examples/transient_transport.py` returns one HTTP 503 response followed by a valid product response and compares the existing naive and resilient controls through the public HTTP endpoint. It exercises dependency injection without provider calls. It is an illustrative transport extension, not a new experimental task or part of the 320-program study.

For a publishable new task: define a new versioned specification, add a scaffold with `create_app(transport, settings=None)`, implement fault responses and behavior-based oracles, add naive and resilient controls, and validate before collecting generated artifacts. Full-study dispatch and the fixed-task analysis require explicit updates; the present analysis assumes T1/T2/T4/T5 with 20 artifacts per cell. Do not silently pool new tasks into that analysis.
