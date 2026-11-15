"""How the MCP server process ends: exit code and stderr tail for stdin EOF, SIGTERM and a closed stdout.
Run in the dev image: python scripts/epipe_repro/server_exit.py"""
import json, os, signal, subprocess, sys, tempfile

TASK = os.environ.get("CADFIX_TASK_DIR", "harbor_tasks/judge/hinge-lid-l2-seed0/environment/task")


def msg(i, method, params=None):
    m = {"jsonrpc": "2.0", "method": method}
    if i is not None:
        m["id"] = i
    if params is not None:
        m["params"] = params
    return (json.dumps(m) + "\n").encode()


INIT = msg(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}) \
    + msg(None, "notifications/initialized")


def run(mode):
    env = {**os.environ, "CADFIX_TASK_DIR": TASK, "CADFIX_OUT_DIR": tempfile.mkdtemp()}
    p = subprocess.Popen([sys.executable, "-m", "cadfix.env.server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env)
    p.stdin.write(INIT + msg(2, "tools/call", {"name": "submit", "arguments": {}}))
    p.stdin.flush()
    p.stdout.readline(); p.stdout.readline()                     # initialize + submit responses
    if mode == "stdin-eof":
        p.stdin.close()
    elif mode == "sigterm":
        p.send_signal(signal.SIGTERM)
    elif mode == "stdout-closed":                                # client gone: reply has nowhere to go
        p.stdout.close()
        p.stdin.write(msg(3, "tools/call", {"name": "list_parts", "arguments": {}}))
        p.stdin.flush()
        try:                                                     # the server should notice and stop by itself
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        try:
            p.stdin.close()
        except BrokenPipeError:
            pass
    try:
        rc = p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill(); rc = "hang"
    err = p.stderr.read().decode(errors="replace").strip().splitlines()
    noise = [l for l in err if "Processing request" not in l]
    print(f"{mode:14s} exit={rc}  stderr: {' | '.join(noise[-3:]) if noise else '(only request log)'}")
    return rc


if __name__ == "__main__":
    codes = [run(m) for m in ("stdin-eof", "sigterm", "stdout-closed")]
    sys.exit(0 if all(c == 0 for c in codes) else 1)
