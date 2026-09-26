# AI Harness

An autonomous coding-agent harness for the AI Harness Hackathon 2026.

## Phase 1: project foundation

This phase establishes the Python package, environment-based configuration, CLI entry point, and the required Makefile interface.

## Phase 2: model interface

The harness sends text tasks through OpenRouter's Responses API. It reads `AI_API_KEY` from the process environment or an ignored local `.env` file. Defaults use `deepseek/deepseek-v3.2` and `https://openrouter.ai/api/v1`; set `AI_MODEL` to use another OpenRouter model.

## Requirements

- Python 3.9 or newer
- `make`

## Setup and launch

```sh
make setup
export AI_API_KEY="<provided key>"
make run
```

The evaluator may provide the API credential through `AI_API_KEY`. Never commit credentials. For local development, copy `.env.example` to `.env` and add your key there; `.env` is ignored by Git. The CLI accepts a task interactively, through `--task`, or on stdin and returns a text response from the configured model.

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

1. **Project foundation (complete):** initialize package structure, Makefile commands, configuration boundaries, and CLI startup.
2. **Model interface (current):** connect to a text model using `AI_API_KEY`; add a provider adapter, prompt handling, and clear model configuration.
3. **Repository understanding and tools:** inspect repository state and files; add safe read, search, edit, and command tools with explicit working-directory boundaries.
4. **Agent orchestration and context:** implement planning, tool-call cycles, context selection, bounded state, and task-completion criteria.
5. **Verification and recovery:** run relevant checks, inspect diffs, handle tool/model failures, retry safely, and report evidence for changes.
6. **Evaluation readiness:** add deterministic evaluation cases, resource limits and logging, document the evaluator workflow, and validate from a clean checkout.

The OpenRouter Responses API endpoint and model identifier follow the provider's current API format. See [OpenRouter's Responses API reference](https://openrouter.ai/docs/api/api-reference/responses/create-responses). The endpoint and model can be changed through environment configuration without source edits.
