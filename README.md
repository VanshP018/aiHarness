# AI Harness

An autonomous coding-agent harness for the AI Harness Hackathon 2026.

## Phase 1: project foundation

This phase establishes the Python package, environment-based configuration, CLI entry point, and the required Makefile interface. The model and provider are deliberately left configurable until the organisers identify the prescribed foundation model and API endpoint.

## Requirements

- Python 3.9 or newer
- `make`

## Setup and launch

```sh
make setup
export AI_API_KEY="<provided key>"
export AI_MODEL="<organiser-prescribed model>"
export AI_BASE_URL="<organiser-prescribed API endpoint>"
make run
```

The evaluator should provide the API credential through `AI_API_KEY`. Never commit credentials. For local development, copy `.env.example` to `.env`; `.env` is ignored by Git. The Phase 1 CLI accepts an issue interactively, through `--task`, or on stdin. Model-backed task execution will be implemented in Phase 2.

```sh
make run
make run ARGS='--repo /path/to/repository --task "Fix the bug described in issue 123"'
```

## Required commands

- `make setup` creates an isolated virtual environment and installs the project.
- `make run` launches the CLI.
- `make test` runs the project's unittest suite.
- `make clean` removes generated local artifacts.

## Development phases

1. **Project foundation (current):** initialize package structure, Makefile commands, configuration boundaries, and CLI startup.
2. **Model interface:** connect to the organiser-prescribed text model using `AI_API_KEY`; add a provider adapter, prompt/message handling, and clear model configuration.
3. **Repository understanding and tools:** inspect repository state and files; add safe read, search, edit, and command tools with explicit working-directory boundaries.
4. **Agent orchestration and context:** implement planning, tool-call cycles, context selection, bounded state, and task-completion criteria.
5. **Verification and recovery:** run relevant checks, inspect diffs, handle tool/model failures, retry safely, and report evidence for changes.
6. **Evaluation readiness:** add deterministic evaluation cases, resource limits and logging, document the evaluator workflow, and validate from a clean checkout.

The attachments do not specify the official model name or endpoint; those need to be set once the organising committee publishes them.
