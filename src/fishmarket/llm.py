"""The only module that talks to the Anthropic API. Modes, cache, ledger, spend guard, FakeLLM."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import permissions
from .config import Config, DEFAULT, PROMPT_VERSION


def _dotenv_value(name: str) -> str:
    """Read one setting from the project .env without exporting or logging its contents."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    try:
        raw = env_path.read_bytes()
        # Notepad/PowerShell may save with a byte-order mark or as UTF-16; handle both so the first key is not missed
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", "replace")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key, separator, value = stripped.partition("=")
            if separator and key.strip() == name:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                return value
    except OSError:
        pass
    return ""


class LLMError(Exception):
    """API trouble (rate limit, network, bad response). Never retried in a loop.
    `call` is set when the API answered and was paid but the answer could not be used."""

    def __init__(self, message: str, call: Optional[dict] = None):
        super().__init__(message)
        self.call = call


class ReplayMiss(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


class CacheCorrupt(LLMError):
    pass


@dataclass
class RunCtx:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    spent_usd: float = 0.0
    calls: int = 0          # every call() made, cached or not
    paid_calls: int = 0     # calls that actually reached the API
    cache_keys: list = field(default_factory=list)   # keys of every answer this run used
    perms: permissions.Usage = field(default_factory=permissions.Usage)   # per-agent call and search counters


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cache_key(model, system, user, tool_schema, max_tokens, temperature) -> str:
    payload = {"model": model, "system": system, "user": user, "tool_schema": tool_schema,
               "max_tokens": max_tokens, "temperature": temperature, "prompt_version": PROMPT_VERSION}
    return hashlib.sha256(_canon(payload).encode("utf-8")).hexdigest()


def load_pricing(cfg: Config) -> dict:
    return json.loads(Path(cfg.PRICING_PATH).read_text())


def compute_cost(pricing: dict, model: str, usage: dict) -> float:
    p = pricing.get(model)
    if p is None:
        raise LLMError(f"No pricing for model {model}; add it to pricing.json.")
    tin, tout = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    cr, cw = usage.get("cache_read_input_tokens", 0) or 0, usage.get("cache_creation_input_tokens", 0) or 0
    cost = (tin * p["input"] + tout * p["output"] + cr * p.get("cache_read", p["input"])
            + cw * p["input"] * 1.25) / 1_000_000
    if tin + cr + cw > p.get("long_prompt_threshold", float("inf")):
        cost *= p.get("long_prompt_multiplier", 1)
    return cost


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _scan(self) -> tuple[float, int]:
        if not self.path.exists():
            return 0.0, 0
        t, bad = 0.0, 0
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                t += float(json.loads(line).get("cost_usd", 0.0))
            except (ValueError, TypeError, AttributeError):
                bad += 1
        return t, bad

    def total(self) -> float:
        """Spend from the readable lines. Check bad_lines(): unreadable lines are not counted."""
        return self._scan()[0]

    def bad_lines(self) -> int:
        return self._scan()[1]

    def append(self, **row) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(_canon(row) + "\n")


class LLM:
    """Real wrapper. `client` can be injected (tests pass a stub); otherwise the SDK is imported lazily."""

    def __init__(self, cfg: Config = DEFAULT, mode: Optional[str] = None, client=None, sleep=time.sleep):
        self.cfg = cfg
        self.mode = mode or cfg.LLM_MODE
        if self.mode not in ("live", "auto", "replay"):
            raise ValueError(f"LLM_MODE must be live, auto or replay (got {self.mode!r})")
        self._client = client
        self.ledger = Ledger(cfg.LEDGER_PATH)
        self.pricing = load_pricing(cfg)
        self._omit_temperature = False

    # -- helpers -------------------------------------------------------
    def _get_client(self):
        if self._client is None:
            key = os.environ.get("ANTHROPIC_API_KEY") or _dotenv_value("ANTHROPIC_API_KEY")
            if not key:
                raise LLMError("ANTHROPIC_API_KEY is not set, and this call is not in the cache. "
                               "Set the key, or use replay mode with cached runs.")
            try:
                import anthropic
            except ImportError as e:  # pragma: no cover
                raise LLMError("The 'anthropic' package is not installed (pip install anthropic).") from e
            # no hidden SDK retries (rule: never loop, every retry is visible) and a bounded wait
            self._client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=self.cfg.LLM_TIMEOUT_S)
        return self._client

    def _cache_paths(self, key: str) -> list[Path]:
        return [self.cfg.CACHE_DIR / f"{key}.json", self.cfg.CACHE_DIR / "approved" / f"{key}.json"]

    def estimate_worst_case(self, model, system, user, tool_schema, max_tokens) -> float:
        p = self.pricing.get(model)
        if p is None:
            raise LLMError(f"No pricing for model {model}; add it to pricing.json.")
        chars = len(system) + len(user) + len(_canon(tool_schema))
        tokens_in = chars / 3.5
        cost = (tokens_in * p["input"] + max_tokens * p["output"]) / 1_000_000
        if tokens_in > p.get("long_prompt_threshold", float("inf")):
            cost *= p.get("long_prompt_multiplier", 1)
        return cost

    def _guard(self, est: float, ctx: RunCtx) -> None:
        bad = self.ledger.bad_lines()
        if bad:
            raise BudgetExceeded(f"The spend ledger has {bad} unreadable line(s), so total spend is unknown. "
                                 f"Fix {self.ledger.path.name} before making live calls.")
        if ctx.spent_usd + est > self.cfg.PER_RUN_LIMIT_USD:
            raise BudgetExceeded(f"This call could push the run over its ${self.cfg.PER_RUN_LIMIT_USD:.2f} limit "
                                 f"(spent ${ctx.spent_usd:.4f}, worst case ${est:.4f}).")
        total = self.ledger.total()
        if total + est > self.cfg.GLOBAL_STOP_USD:
            raise BudgetExceeded(f"This call could push total spend over the ${self.cfg.GLOBAL_STOP_USD:.2f} "
                                 f"stop (ledger shows ${total:.2f}).")

    def remaining_budget(self) -> float:
        total, bad = self.ledger._scan()
        return 0.0 if bad else max(0.0, self.cfg.GLOBAL_STOP_USD - total)

    def _read_cache(self, p: Path) -> dict:
        """A saved answer, or CacheCorrupt. A damaged file is renamed to .corrupt so it is never served."""
        try:
            hit = json.loads(p.read_text())
            usage = hit["usage"]
            int(usage["input_tokens"]), int(usage["output_tokens"])
            if not isinstance(hit["tool_input"], dict):
                raise TypeError("tool_input is not an object")
            return hit
        except (ValueError, KeyError, TypeError) as e:
            bad = p.with_suffix(".corrupt")
            p.replace(bad)
            raise CacheCorrupt(f"The saved answer {p.name} is unreadable ({type(e).__name__}); "
                               f"it was moved to {bad.name} and not used.") from e

    # -- main entry ----------------------------------------------------
    def call(self, agent: str, system: str, user: str, tool_schema: dict, model: str, max_tokens: int,
             run_ctx: RunCtx) -> dict:
        # boundary check first: an agent outside its permissions never reaches the cache or the API
        permissions.check_call(agent, tool_schema, max_tokens, self.estimate_worst_case(model, system, user, tool_schema, max_tokens), run_ctx.perms)
        run_ctx.calls += 1
        temperature = None if (self._omit_temperature or self.cfg.TEMPERATURE is None) else self.cfg.TEMPERATURE
        key = cache_key(model, system, user, tool_schema, max_tokens, temperature)
        run_ctx.cache_keys.append(key)

        if self.mode in ("auto", "replay"):
            for p in self._cache_paths(key):
                if p.exists():
                    hit = self._read_cache(p)
                    self.ledger.append(ts=_now(), run_id=run_ctx.run_id, agent=agent, model=model,
                                       input_tokens=hit["usage"]["input_tokens"],
                                       output_tokens=hit["usage"]["output_tokens"], cache="hit", cost_usd=0.0,
                                       mode=self.mode)
                    return {"tool_input": hit["tool_input"], "usage": hit["usage"], "cost_usd": 0.0,
                            "cache": "hit", "model": model}
            if self.mode == "replay":
                raise ReplayMiss(f"Replay mode: no saved answer for the {agent} call. "
                                 "Switch to auto mode to make a live call, or run scripts/approve.py after a live run.")

        self._guard(self.estimate_worst_case(model, system, user, tool_schema, max_tokens), run_ctx)
        omitted_before = self._omit_temperature
        usage, tool_input, stop_reason = self._live(system, user, tool_schema, model, max_tokens, temperature)
        notes = ["temperature_dropped"] if self._omit_temperature and not omitted_before else []
        # The API answered, so the call is paid: count it before deciding whether the answer is usable.
        cost = compute_cost(self.pricing, model, usage)
        run_ctx.spent_usd += cost
        run_ctx.paid_calls += 1
        outcome = "truncated" if stop_reason == "max_tokens" else "no_tool_call" if tool_input is None else "ok"
        self.ledger.append(ts=_now(), run_id=run_ctx.run_id, agent=agent, model=model,
                           input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                           cache="miss", cost_usd=round(cost, 8), mode=self.mode, outcome=outcome)
        result = {"tool_input": tool_input, "usage": usage, "cost_usd": cost, "cache": "miss", "model": model,
                  "notes": notes}
        if outcome == "truncated":
            raise LLMError(f"The answer was cut off at the {max_tokens}-token limit, so it was not used.", result)
        if outcome == "no_tool_call":
            raise LLMError("The AI service did not return the structured answer we asked for.", result)
        self.cfg.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (self.cfg.CACHE_DIR / f"{key}.json").write_text(_canon({
            "agent": agent, "model": model, "prompt_version": PROMPT_VERSION, "tool_input": tool_input,
            "usage": usage, "cost_usd": cost}))
        return result

    def search_call(self, agent: str, system: str, user: str, model: str, max_tokens: int, run_ctx: RunCtx,
                    max_uses: int, allowed_domains: list[str] | None = None, blocked_domains: list[str] | None = None) -> dict:
        """One request with Anthropic's server-side web search tool. Returns the response blocks as plain dicts.
        Cached and ledgered like call(); the spend guard counts the per-search fee and worst-case search tokens.
        Only agents whose policy allows the web may use it, within their per-run search allowance."""
        p = self.pricing.get(model)
        if p is None:
            raise LLMError(f"No pricing for model {model}; add it to pricing.json.")
        tokens_in = (len(system) + len(user)) / 3.5 + max_uses * self.cfg.WEB_TOKENS_PER_SEARCH
        est = (tokens_in * p["input"] + max_tokens * p["output"]) / 1_000_000 + max_uses * self.cfg.WEB_SEARCH_USD
        permissions.check_search(agent, max_uses, max_tokens, est, run_ctx.perms, allowed_domains, blocked_domains)
        run_ctx.calls += 1
        tool = {"type": self.cfg.WEB_SEARCH_TOOL, "name": "web_search", "max_uses": int(max_uses)}
        if allowed_domains:
            tool["allowed_domains"] = list(allowed_domains)
        if blocked_domains:
            tool["blocked_domains"] = list(blocked_domains)
        key = cache_key(model, system, user, tool, max_tokens, None)
        run_ctx.cache_keys.append(key)
        if self.mode in ("auto", "replay"):
            for p in self._cache_paths(key):
                if p.exists():
                    hit = json.loads(p.read_text())
                    self.ledger.append(ts=_now(), run_id=run_ctx.run_id, agent=agent, model=model, input_tokens=hit["usage"].get("input_tokens", 0),
                                       output_tokens=hit["usage"].get("output_tokens", 0), cache="hit", cost_usd=0.0, mode=self.mode)
                    run_ctx.perms.searches[agent] = run_ctx.perms.searches.get(agent, 0) + int(hit.get("searches", 0))
                    return {"blocks": hit["blocks"], "usage": hit["usage"], "searches": hit.get("searches", 0), "cost_usd": 0.0, "cache": "hit"}
            if self.mode == "replay":
                raise ReplayMiss(f"Replay mode: no saved answer for the {agent} web search.")
        self._guard(est, run_ctx)
        client = self._get_client()
        try:
            resp = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                          messages=[{"role": "user", "content": user}], tools=[tool])
        except Exception as e:
            raise LLMError(f"The web search request failed ({type(e).__name__}): {_safe(e)}") from e
        blocks = _plain(list(resp.content))
        u = resp.usage
        usage = {"input_tokens": int(getattr(u, "input_tokens", 0) or 0), "output_tokens": int(getattr(u, "output_tokens", 0) or 0)}
        stu = getattr(u, "server_tool_use", None)
        searches = int(getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
        if not searches:
            searches = sum(1 for b in blocks if b.get("type") == "server_tool_use" and b.get("name") == "web_search")
        run_ctx.perms.searches[agent] = run_ctx.perms.searches.get(agent, 0) + searches
        cost = compute_cost(self.pricing, model, usage) + searches * self.cfg.WEB_SEARCH_USD
        run_ctx.spent_usd += cost
        run_ctx.paid_calls += 1
        self.ledger.append(ts=_now(), run_id=run_ctx.run_id, agent=agent, model=model, input_tokens=usage["input_tokens"],
                           output_tokens=usage["output_tokens"], cache="miss", cost_usd=round(cost, 8), mode=self.mode, web_searches=searches)
        self.cfg.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (self.cfg.CACHE_DIR / f"{key}.json").write_text(_canon({"agent": agent, "model": model, "blocks": blocks, "usage": usage,
                                                                 "searches": searches, "cost_usd": cost}))
        return {"blocks": blocks, "usage": usage, "searches": searches, "cost_usd": cost, "cache": "miss"}

    def _live(self, system, user, tool_schema, model, max_tokens, temperature):
        client = self._get_client()
        sys_arg = ([{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
                   if self.cfg.ENABLE_PROMPT_CACHING else system)
        kwargs = dict(model=model, max_tokens=max_tokens, system=sys_arg,
                      messages=[{"role": "user", "content": user}], tools=[tool_schema],
                      tool_choice={"type": "tool", "name": tool_schema["name"]})
        if model in self.cfg.AUTO_TOOL_CHOICE_MODELS:
            # A forced tool call is a 400 here. The prompt says to reply only through the tool; a reply without
            # a tool call is counted and raises LLMError, so the pipeline falls back visibly.
            kwargs["tool_choice"] = {"type": "auto"}
            kwargs["thinking"] = {"type": "between_tools"}   # thinking off, so it cannot eat max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        try:
            try:
                resp = client.messages.create(**kwargs)
            except Exception as e:
                # Some models reject `temperature`. Drop it once and remember; never loop.
                if temperature is not None and "temperature" in str(e).lower():
                    self._omit_temperature = True
                    kwargs.pop("temperature")
                    resp = client.messages.create(**kwargs)
                else:
                    raise
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"The AI service returned an error ({type(e).__name__}): {_safe(e)}") from e
        block = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
        u = resp.usage
        usage = {"input_tokens": int(getattr(u, "input_tokens", 0) or 0),
                 "output_tokens": int(getattr(u, "output_tokens", 0) or 0)}
        for k in ("cache_read_input_tokens", "cache_creation_input_tokens"):
            v = getattr(u, k, 0)
            if v:
                usage[k] = int(v)
        return usage, (dict(block.input) if block is not None else None), getattr(resp, "stop_reason", None)


def _plain(obj):
    """SDK objects (or test stand-ins) to plain dicts/lists, so blocks can be cached and inspected."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {k: _plain(v) for k, v in vars(obj).items()}
    return obj


def _safe(e: Exception) -> str:
    """Error text with any key-looking token removed."""
    import re
    return re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "[redacted]", str(e))[:300]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FakeLLM:
    """Free stand-in for tests and offline demos. `handlers[agent]` is called as
    handler(system, user, tool_schema, attempt) and returns the tool_input dict, or raises LLMError.
    Counts calls per agent; a handler may inspect `attempt` (1-based) to script failures."""

    def __init__(self, handlers: dict[str, Callable]):
        self.handlers = handlers
        self.log: list[dict] = []
        self.mode = "fake"

    def remaining_budget(self) -> float:
        return float("inf")

    def call(self, agent, system, user, tool_schema, model, max_tokens, run_ctx: RunCtx) -> dict:
        permissions.check_call(agent, tool_schema, max_tokens, 0.0, run_ctx.perms)
        run_ctx.calls += 1
        attempt = 1 + sum(1 for x in self.log if x["agent"] == agent)
        out = self.handlers[agent](system, user, tool_schema, attempt)
        self.log.append({"agent": agent, "attempt": attempt, "user": user})
        usage = {"input_tokens": max(1, (len(system) + len(user)) // 4), "output_tokens": 150}
        return {"tool_input": out, "usage": usage, "cost_usd": 0.0, "cache": "miss", "model": model}
