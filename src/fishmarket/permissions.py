"""What each AI agent is allowed to do. llm.py checks every request against this table before it is sent,
so a prompt (or text injected into one) can never widen an agent's abilities.

Roles, kept deliberately different:
- agent1 (planner): picks a catalogue entry or data sources. One structured answer. No web.
- agent2 (analyst): explains Python's numbers and any quoted evidence. One structured answer. No web, ever.
- summary (writer): writes the short summary from checked claims. One structured answer. No web.
- researcher: the ONLY agent that may search the web. It returns quotes and links, never a structured
  recommendation; Python keeps only the quoted citation text. It cannot call any of the other agents' tools.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class PermissionDenied(Exception):
    """An agent asked for something outside its boundary. Raised before any request is sent, so nothing is paid."""


@dataclass(frozen=True)
class AgentPolicy:
    role: str
    tools: frozenset = frozenset()          # structured-answer tool names this agent may be forced to use
    web: bool = False                        # may use the server-side web search tool
    max_searches_per_run: int = 0            # across all of this agent's calls in one run
    max_tokens: int = 0                      # hard ceiling on the output size it may ask for
    max_calls_per_run: int = 0               # paid or cached calls by this agent in one run
    max_usd_per_call: float = 0.0            # worst-case estimate must stay under this


POLICIES: dict[str, AgentPolicy] = {
    "agent1": AgentPolicy("planner", frozenset({"submit_plan", "choose_entry"}), max_tokens=800, max_calls_per_run=6, max_usd_per_call=0.03),
    "agent2": AgentPolicy("analyst", frozenset({"submit_analysis"}), max_tokens=3000, max_calls_per_run=3, max_usd_per_call=0.10),
    "summary": AgentPolicy("writer", frozenset({"submit_summary"}), max_tokens=1600, max_calls_per_run=8, max_usd_per_call=0.05),
    "researcher": AgentPolicy("researcher", frozenset(), web=True, max_searches_per_run=3, max_tokens=1500, max_calls_per_run=2, max_usd_per_call=0.12),
}

ROOT = Path(__file__).resolve().parents[2]
TRUSTED_FILE = ROOT / "data_real" / "web_trusted_domains.txt"
BLOCKED_FILE = ROOT / "data_real" / "web_blocked_domains.txt"


def _domains(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        d = line.split("#", 1)[0].strip().lower()
        if d and "/" not in d and ":" not in d:
            out.append(d)
    return list(dict.fromkeys(out))


def trusted_domains() -> list[str]:
    return _domains(TRUSTED_FILE)


def blocked_domains() -> list[str]:
    return _domains(BLOCKED_FILE)


def policy(agent: str) -> AgentPolicy:
    p = POLICIES.get(agent)
    if p is None:
        raise PermissionDenied(f"'{agent}' is not a known agent, so it has no permissions.")
    return p


@dataclass
class Usage:
    """Per-run counters, kept on the RunCtx."""
    calls: dict = field(default_factory=dict)
    searches: dict = field(default_factory=dict)


def check_call(agent: str, tool_schema: dict, max_tokens: int, est_usd: float, usage: Usage) -> None:
    p = policy(agent)
    name = (tool_schema or {}).get("name", "")
    if name not in p.tools:
        raise PermissionDenied(f"The {p.role} ({agent}) may not use the tool '{name}'.")
    _common(agent, p, max_tokens, est_usd, usage)


def check_search(agent: str, max_uses: int, max_tokens: int, est_usd: float, usage: Usage,
                 allowed: list[str] | None, blocked: list[str] | None) -> None:
    p = policy(agent)
    if not p.web:
        raise PermissionDenied(f"The {p.role} ({agent}) is not allowed to search the web.")
    if allowed and blocked:
        raise PermissionDenied("A web search may set allowed or blocked sites, not both.")
    if not allowed and not blocked:
        raise PermissionDenied("An open-web search must carry the blocked-sites list.")
    left = p.max_searches_per_run - usage.searches.get(agent, 0)
    if max_uses < 1 or max_uses > left:
        raise PermissionDenied(f"The {p.role} has {max(left, 0)} web search(es) left in this run (asked for {max_uses}).")
    _common(agent, p, max_tokens, est_usd, usage)


def _common(agent, p, max_tokens, est_usd, usage) -> None:
    if max_tokens > p.max_tokens:
        raise PermissionDenied(f"The {p.role} may ask for at most {p.max_tokens} output tokens (asked for {max_tokens}).")
    if usage.calls.get(agent, 0) >= p.max_calls_per_run:
        raise PermissionDenied(f"The {p.role} has used its {p.max_calls_per_run} calls for this run.")
    if est_usd > p.max_usd_per_call:
        raise PermissionDenied(f"The {p.role}'s call could cost up to ${est_usd:.3f}, over its ${p.max_usd_per_call:.2f} per-call limit.")
    usage.calls[agent] = usage.calls.get(agent, 0) + 1
