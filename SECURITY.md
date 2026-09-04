# Security policy

DepFailBench executes generated Python code and therefore must be run only with artifacts from trusted research workflows, preferably inside an isolated container or disposable environment. The Docker image improves reproducibility but is not a security sandbox.

Never place API keys in prompts, artifact metadata, source files, or raw-response files. Report suspected credential exposure privately to the repository maintainers before opening a public issue.
