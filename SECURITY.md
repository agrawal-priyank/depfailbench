# Security policy

DepFailBench executes generated Python code and therefore must be run only with artifacts from trusted research workflows, preferably inside an isolated container or disposable environment. The Docker image improves reproducibility but is not a security sandbox.

Never place API keys in prompts, artifact metadata, source files, or raw-response files. The evaluator's environment-name filter is a best-effort backstop, not a substitute for a credential-free isolated environment. Report suspected credential exposure privately to [agrawalpriyank@icloud.com](mailto:agrawalpriyank@icloud.com) before opening a public issue.
