"""Shell command execution tool.

SAFETY NOTE: run_command executes arbitrary shell commands on the host with
the permissions of the server process, with no sandboxing beyond a timeout.
Only enable/register this tool in trusted contexts (e.g. local development),
never expose this server to untrusted clients or networks.
"""

import subprocess

DEFAULT_TIMEOUT = 30


def run_command(command: str, cwd: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run a shell command and return its stdout, stderr, and exit code.

    `cwd` optionally sets the working directory; `timeout` is in seconds.
    The command runs through the system shell (`sh -c`), so use shell
    quoting/escaping as you would on the command line.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s: {command}"

    parts = [f"$ {command}", f"exit code: {result.returncode}"]
    if result.stdout:
        parts.append(f"--- stdout ---\n{result.stdout.rstrip()}")
    if result.stderr:
        parts.append(f"--- stderr ---\n{result.stderr.rstrip()}")
    return "\n".join(parts)
