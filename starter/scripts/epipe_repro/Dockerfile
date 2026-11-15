# EPIPE reproduction: OpenCode 1.19.5's MCP stdio client (MCP SDK 1.29.0 on Bun 1.4.4) against our MCP server.
# No model, no OpenCode: repro.mjs replays an episode and then OpenCode's shutdown sequence.
FROM oven/bun:1.4.4 AS bun
FROM cadfix-dev
COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun
WORKDIR /repro
RUN echo '{"type":"module","dependencies":{"@modelcontextprotocol/sdk":"1.29.0"}}' > package.json && bun install
COPY repro.mjs /repro/
