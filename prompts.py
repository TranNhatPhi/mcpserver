"""MCP prompts: reusable prompt templates exposed to clients."""


def register(mcp):
    @mcp.prompt()
    def summarize_file(path: str) -> str:
        """Ask the model to read and summarize a file at the given path."""
        return (
            f"Please read the file at '{path}' (use the read_file tool) "
            "and give me a concise summary of its purpose and contents, "
            "highlighting anything that looks important or unusual."
        )

    @mcp.prompt()
    def code_review(diff: str) -> str:
        """Ask the model to review a code diff for bugs and improvements."""
        return (
            "Please review the following code diff. Point out correctness "
            "bugs first, then suggest simplifications or efficiency "
            "improvements. Be concise and reference specific lines.\n\n"
            f"```diff\n{diff}\n```"
        )
