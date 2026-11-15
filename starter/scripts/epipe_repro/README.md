# EPIPE reproduction (OpenCode `NonZeroAgentExitCodeError`)

In job `jobs/2026-11-15__06-48-21`, 4 of 9 OpenCode trials exited 1 with `EPIPE: broken pipe, write` after
`submit` (see `docs/RUN_ANALYSIS_sonnet55.md`, section 3). This checks whether our MCP server causes it, without
a model and without OpenCode.

- `repro.mjs`: OpenCode 1.19.5's MCP client stack (MCP SDK 1.29.0 `StdioClientTransport`, stderr `"pipe"`, on Bun
  1.4.4). It plays a short episode (get_task, list_parts, run_check_S1_opening, test_fit, submit) and then
  OpenCode's shutdown (SIGTERM to the server's descendants, `client.close()`). Modes:
  - `normal`
  - `sigterm-first`: the server is killed while a request is still being written
  - `server-dies`: SIGKILL, then a write
- `run.sh N`: runs each mode N times and counts non-zero exits and EPIPE.
- `server_exit.py`: the server's own exit code for stdin EOF, SIGTERM and a closed stdout. It is also used by
  `tests/test_mcp.py`.

```bash
docker build -t cadfix-dev . && docker build -t cadfix-epipe scripts/epipe_repro
docker run --rm -v "$PWD":/app cadfix-epipe bash /app/scripts/epipe_repro/run.sh 20
docker run --rm -v "$PWD":/app cadfix-dev python scripts/epipe_repro/server_exit.py
```

Results on 2026-11-15:

| Server | `run.sh 20` (60 runs) | stdin EOF | SIGTERM | stdout closed |
|---|---|---|---|---|
| before | 0 EPIPE, 0 non-zero exits | exit 0 | exit -15 (killed) | exit 1, `BrokenPipeError` traceback |
| after (graceful shutdown in `cadfix/env/server.py`) | 0 EPIPE, 0 non-zero exits | exit 0 | exit 0 | exit 0 |

The SDK client handles every way the server can go away, so the EPIPE comes from somewhere else inside OpenCode,
not from its MCP connection to us. The graceful shutdown is kept anyway, together with WARNING-level logging:
OpenCode pipes the server's stderr and never reads it.
