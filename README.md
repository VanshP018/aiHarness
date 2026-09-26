# AI Harness

An autonomous coding-agent harness for the AI Harness Hackathon 2026.

## Phase 1: project foundation

This phase establishes the Python package, environment-based configuration, CLI entry point, and the required Makefile interface.

## Phase 2: model interface

The harness sends text tasks through OpenRouter. It reads `AI_API_KEY` from the process environment or an ignored local `.env` file. Defaults use `deepseek/deepseek-v3.2` and `https://openrouter.ai/api/v1`; set `AI_MODEL` to use another OpenRouter model. Direct text requests use `/responses`; the agent loop uses `/chat/completions` for function calling.

## Phase 3: repository tools

`RepositoryTools` provides bounded file listing, UTF-8 file reading, literal text search, atomic file writing, and non-shell command execution scoped to the selected repository. It excludes Git internals, generated directories, `.env` files, and common key file types. Command subprocesses receive a minimal environment that omits `AI_API_KEY`. These path and process controls reduce accidental exposure but do not provide an OS-level sandbox.

Use `make run ARGS='--repo /path/to/repository --inspect'` to print a compact repository inventory without contacting the model.

## Phase 4: agent orchestration and context

The coding agent sends the task to the model with repository-tool definitions, executes requested tools, returns their results to the model, and repeats until it receives a final response. The loop is bounded to 24 model turns and 20 tool calls per task, requests one tool call at a time, limits tasks to 30,000 characters, truncates each tool result to 12,000 characters, and drops older complete tool exchanges when conversation history grows past 80,000 characters. Run `make run ARGS='--repo /path/to/repository --task \"Describe and fix the bug\"'` to start an agent task. Tool names are printed as they execute; the final response reports the result.

## Safety and focused context

Build mode is the default. Repository reads are available directly; before any file edit or command, the CLI asks whether to allow it once, allow that exact action for the current run, or deny it. Without an interactive terminal, these actions are denied. `--mode review` gives the model read-only repository tools, which is useful for code review.

Before each file write, the harness saves that file's previous contents under the ignored `.aiharness/snapshots/` directory. Snapshots are local and are not committed. List them with `make run ARGS='--repo /path/to/repository --list-snapshots'`; restore the newest with `make run ARGS='--repo /path/to/repository --restore'` or choose an ID with `--restore SNAPSHOT_ID`. Restore asks for confirmation and saves the current version as a rollback snapshot first.

At startup the agent receives a concise repository file map and, when present, the root `AGENTS.md` or `AIHARNES.md`. It is instructed to inspect focused files before editing, run relevant checks after edits, repair failures, and report checks that were skipped or remain failing. Project guidance cannot override tool permissions.

The repository tools constrain paths and command execution but are not an OS-level sandbox. Approve commands only when you understand what they will run.

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
make run ARGS='--repo /path/to/repository --event-log .aiharness/events.jsonl --task "Fix a bug"'
```

## Running the Test Suite

The project includes a comprehensive test suite that validates the core functionality of the AI Harness. To run the tests:

### Basic Test Execution

```sh
# First, set up the virtual environment if you haven't already
make setup

# Run all tests with verbose output
make test
```

The `make test` command runs the Python unittest framework in the project's virtual environment, discovering and executing all test cases in the `tests/` directory with verbose output.

**Expected output:** When tests pass, you'll see each test name followed by `... ok` and a summary like:
```
Ran 23 tests in 0.049s
OK
```

### Test Coverage

The test suite includes:

1. **`test_agent.py`** - Tests for the `CodingAgent` class including:
   - Tool execution and model interaction
   - Context trimming and management
   - Build mode and review mode behaviors
   - Invalid tool argument handling

2. **`test_permissions.py`** - Tests for the `PermissionManager` class:
   - Read permissions without prompts
   - Review mode read-only restrictions
   - Session approval scoping
   - Deny caching behavior

3. **`test_repository_tools.py`** - Tests for the `RepositoryTools` class:
   - File listing and filtering of secrets/generated directories
   - File reading with UTF-8 encoding and size limits
   - Text search functionality
   - File writing and snapshot management
   - Path security and escape prevention
   - Command execution with environment isolation

4. **`test_event_log.py`** - Tests that event logs capture tool outcomes without recording arguments or output.

### Running Individual Test Files

You can run specific test files or modules using Python directly:

```sh
# Run a specific test file
python -m unittest tests/test_agent.py -v

# Run tests for a specific test class
python -m unittest tests.test_agent.CodingAgentTests -v

# Run a specific test method
python -m unittest tests.test_agent.CodingAgentTests.test_agent_executes_tool_then_returns_model_final -v
```

**Note:** These commands should be run from within the virtual environment (`source .venv/bin/activate` on Unix or `.venv\Scripts\activate` on Windows) or prefixed with `.venv/bin/python` if not activated.

### Test Environment

The test suite:
- Uses temporary directories for isolation
- Mocks external API calls to avoid network dependencies
- Tests edge cases including invalid inputs and security boundaries
- Verifies all tool functionality works correctly within the harness constraints

### Troubleshooting

If tests fail:

1. **Ensure the virtual environment is set up:** Run `make setup` to create a fresh environment
2. **Check for syntax errors:** Run `python -m py_compile src/aiharness/*.py tests/*.py` to check for basic syntax issues
3. **Run tests in isolation:** Try running individual test files to identify which specific test is failing
4. **Check Python version:** Ensure you're using Python 3.9 or newer

After making changes to the codebase, running `make test` ensures that existing functionality remains intact.

## Offline Evaluations

Run `make eval` to execute deterministic, end-to-end workflow evaluations. They use a scripted model client and temporary repositories, so they require no OpenRouter API key or network access. The scenarios check that denied edits do not change files, a failed verification can be followed by a repair and passing check, and the tool-call limit stops an unbounded run.

Use `--event-log PATH` to write optional JSONL activity records. The log contains timestamps, tool names, and outcomes or command exit codes; it omits task text, tool arguments, file contents, command output, and model responses. The log rotates at 5 MB and keeps one previous file alongside it. The default `.aiharness/` directory is ignored by Git.

Before submitting a change, run both `make test` and `make eval`. For a clean-checkout validation, clone the repository, run `make setup`, then run those two commands from the clone. Keep API credentials out of evaluation fixtures and logs.

## Required commands

- `make setup` creates an isolated virtual environment and installs the project.
- `make run` launches the CLI.
- `make test` runs the project's unittest suite.
- `make eval` runs deterministic offline workflow evaluations.
- `make clean` removes generated local artifacts.

## Development phases

1. **Project foundation (complete):** initialize package structure, Makefile commands, configuration boundaries, and CLI startup.
2. **Model interface (complete):** connect to a text model using `AI_API_KEY`; add a provider adapter, prompt handling, and clear model configuration.
3. **Repository understanding and tools (complete):** inspect repository state and files; add bounded read, search, edit, and command tools with explicit working-directory boundaries.
4. **Agent orchestration and context (complete):** implement bounded tool-call cycles, repository maps, project guidance, and a focused context window.
5. **Safety, verification and recovery (complete):** per-action approvals, read-only review, pre-edit snapshots, and verify/recover guidance are in place.
6. **Evaluation readiness (complete):** deterministic offline scenarios, bounded execution, optional redacted event logs, evaluator instructions, and clean-checkout validation.

The OpenRouter endpoints and model identifier follow the provider's API formats. See the [Responses API reference](https://openrouter.ai/docs/api/api-reference/responses/create-responses) and [tool-calling guide](https://openrouter.ai/docs/guides/features/tool-calling). The endpoint and model can be changed through environment configuration without source edits.
