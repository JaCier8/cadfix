// Replays an agent episode over MCP stdio exactly like OpenCode 1.19.5 (StdioClientTransport, stderr "pipe" that
// nobody reads), then OpenCode's shutdown: SIGTERM to the server's descendants (pgrep -P), client.close(), exit.
// An unhandled stream error (EPIPE) makes this process exit non-zero, as it does OpenCode.
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { execFileSync } from "node:child_process";

const mode = process.argv[2] || "normal";   // normal | sigterm-first | server-dies
const transport = new StdioClientTransport({ stderr: "pipe", command: "python3", args: ["-m", "cadfix.env.server"],
                                            env: { ...process.env } });
const client = new Client({ name: "repro", version: "0" });
await client.connect(transport);
await client.listTools();
for (const name of ["get_task", "list_parts", "run_check_S1_opening", "test_fit", "submit"])
  await client.callTool({ name, arguments: {} });
const pid = transport.pid;
if (mode === "sigterm-first") process.kill(pid, "SIGTERM");          // server killed while the client still writes
if (mode === "server-dies") { process.kill(pid, "SIGKILL"); await new Promise(r => setTimeout(r, 200)); }
try { for (const c of execFileSync("pgrep", ["-P", String(pid)]).toString().split("\n").filter(Boolean))
        process.kill(Number(c), "SIGTERM"); } catch {}
if (mode !== "normal") client.callTool({ name: "list_parts", arguments: {} }).catch(() => {});   // in-flight write
await client.close();
console.log("closed ok");
