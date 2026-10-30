"""All tunable settings. Every value can be overridden: build a Config with dataclasses.replace()."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DECISION_QUESTION = "Should I sell now or hold over the next 3 months?"
QUESTION_TYPES = ("sell_or_hold", "buy_now_or_wait", "best_months", "compare_markets", "best_buyer_type")
QUESTION_LABELS = {
    "sell_or_hold": "Should I sell now or hold over the next 3 months?",
    "buy_now_or_wait": "Should I buy now or wait over the next 3 months?",
    "best_months": "Which are the best months to fish or harvest?",
    "compare_markets": "Which market pays me the most after fees and freight?",
    "best_buyer_type": "Which type of buyer should I sell to?",
}
AGENTS = ("agent1", "agent2", "summary")

PROMPT_VERSION = "p5"  # bump whenever a prompt in agents/prompts/ changes


@dataclass(frozen=True)
class Config:
    AS_OF_DEFAULT: str = "2026-10-15"
    WEB_MAX_SEARCHES: int = 3               # web research: total searches per question (trusted sites first, then open web)
    WEB_SEARCH_USD: float = 0.01            # Anthropic web search fee per search ($10 per 1,000)
    WEB_TOKENS_PER_SEARCH: int = 25000      # worst-case input tokens a search adds, for the spend guard
    WEB_SEARCH_TOOL: str = "web_search_20250305"
    SCENARIO_REAL_CONTEXT: bool = True      # give the scenario agents words-only real U.S. background (scenario_context.py)
    HOLD_THRESHOLD: float = 1.10
    BUY_THRESHOLD: float = 1.05
    WAIT_THRESHOLD: float = 0.95
    SQUEEZE_PTS: float = 5.0
    MARKET_STALE_FACTOR: float = 2.0
    SEASON_VOL_EXPONENT: float = 0.5
    CARRY_APR: float = 0.08
    QUALITY_WINDOW_START: str = "2026-04-01"
    QUALITY_VERIFIED_SHARE: float = 0.8
    QUALITY_PARTIAL_SHARE: float = 0.4
    OZ_PER_LB: float = 16.0
    NOTE_MAX_CHARS: int = 1000
    MAX_SPECIES: int = 3
    TREND_THRESHOLD_PCT: float = 2.0
    SEASONALITY_STRONG_SPREAD: float = 0.18
    STALE_FACTOR: float = 2.0
    AGING_FACTOR: float = 1.5
    MAX_DATA_AGE_MONTHS: int = 3
    OUTLIER_HIGH: float = 2.0
    OUTLIER_LOW: float = 0.5
    OUTLIER_WINDOW_DAYS: int = 186      # about plus or minus 6 months
    OUTLIER_MIN_NEIGHBOURS: int = 3
    KG_TO_LB: float = 2.2046
    MIN_CLEAN_MONTHS: int = 24
    DISAGREEMENT_MEDIAN_PCT: float = 10.0
    DISAGREEMENT_MONTHS: int = 6
    DISAGREEMENT_MIN_OVERLAP: int = 3
    MAX_TOKENS: dict = field(default_factory=lambda: {"agent1": 600, "agent2": 2600, "summary": 1400, "researcher": 1200})
    LLM_TIMEOUT_S: float = 60.0        # one API request; the SDK default is 10 minutes
    PER_RUN_LIMIT_USD: float = 0.25
    GLOBAL_STOP_USD: float = 34.00
    MODEL_MIX: dict = field(default_factory=lambda: {
        "dev": {"agent1": "claude-haiku-5-5", "agent2": "claude-haiku-5-5", "summary": "claude-haiku-5-5", "researcher": "claude-haiku-5-5"},
        "final": {"agent1": "claude-haiku-5-5", "agent2": "claude-sonnet-5-5", "summary": "claude-haiku-5-5", "researcher": "claude-haiku-5-5"},
    })
    LLM_MODE: str = field(default_factory=lambda: os.environ.get("LLM_MODE", "auto"))
    # Models that return a 400 for a forced tool_choice: they get tool_choice auto, thinking off.
    AUTO_TOOL_CHOICE_MODELS: tuple = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1")
    TEMPERATURE: float | None = None   # Claude Haiku 5.5 and later reject non-default sampling values (400)
    ENABLE_PROMPT_CACHING: bool = False
    # locations (tests point these at temp folders)
    DATA_DIR: Path = field(default_factory=lambda: Path(os.environ.get("FISHMARKET_DATA_DIR", ROOT / "fishmarket_data")))
    CACHE_DIR: Path = ROOT / "cache"
    LEDGER_PATH: Path = ROOT / "ledger.jsonl"
    RUNS_DIR: Path = ROOT / "runs"
    PRICING_PATH: Path = ROOT / "pricing.json"
    PRESETS_PATH: Path = ROOT / "app" / "presets.json"


DEFAULT = Config()
