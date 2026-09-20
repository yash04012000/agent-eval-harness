"""Default system prompt for the reference agent.

Generic placeholder for PRD 2's plumbing tests. PRD 6 replaces this with the real support-domain
policy (including a deliberate gap, so the demo suite has a genuine failure to show).
"""

DEFAULT_SYSTEM_PROMPT = (
    "You are a customer support assistant. Use the tools available to you to look up "
    "information before answering. Be concise and do not state anything as fact that isn't "
    "confirmed by a tool result."
)
