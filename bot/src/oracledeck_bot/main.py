
import argparse
import asyncio
import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import dotenv
import httpx

from forecasting_tools import (
    BinaryPrediction,
    BinaryQuestion,
    ConditionalPrediction,
    ConditionalQuestion,
    DatePercentile,
    DateQuestion,
    ForecastBot,
    GeneralLlm,
    MetaculusClient,
    MetaculusQuestion,
    MultipleChoiceQuestion,
    NumericDistribution,
    NumericQuestion,
    Percentile,
    PredictionAffirmed,
    PredictionTypes,
    PredictedOptionList,
    ReasonedPrediction,
    clean_indents,
    structure_output,
)

dotenv.load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model identifiers — unchanged from original
# ---------------------------------------------------------------------------
_CLAUDE_MODEL = "openrouter/anthropic/claude-sonnet-4-6"
_GPT_MODEL    = "openrouter/openai/gpt-5.4"

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
METACULUS_TOKEN    = os.getenv("METACULUS_TOKEN", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
EXA_API_KEY        = os.getenv("EXA_API_KEY", "")
TINYFISH_API_KEY   = os.getenv("TINYFISH_API_KEY", "")
BACKEND_URL        = os.getenv("BACKEND_URL", "").rstrip("/")


# ---------------------------------------------------------------------------
# Exa search client
# Docs: https://docs.exa.ai/reference/search
# Used for: high-quality semantic web search with highlights + summaries
# ---------------------------------------------------------------------------

class ExaSearcher:
    """
    Wraps the Exa neural search API.
    Returns rich results with per-result summaries and sentence highlights.
    Used as the primary research source for OracleDeck forecasts.
    """

    BASE_URL = "https://api.exa.ai"

    def __init__(
        self,
        api_key: str,
        num_results: int = 5,
        highlight_sentences: int = 3,
        timeout_s: int = 30,
    ):
        self.api_key = api_key
        self.num_results = num_results
        self.highlight_sentences = highlight_sentences
        self.timeout_s = timeout_s

    async def search(self, query: str) -> list[dict[str, Any]]:
        """
        Run a single Exa search query.
        Returns list of result dicts with keys:
          title, url, summary, highlights, publishedDate
        """
        if not self.api_key:
            logger.warning("[Exa] No EXA_API_KEY set — skipping search")
            return []

        payload = {
            "query": query,
            "numResults": self.num_results,
            "contents": {
                "summary": {"query": query},
                "highlights": {
                    "numSentences": self.highlight_sentences,
                    "highlightsPerUrl": 2,
                },
            },
            "useAutoprompt": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/search",
                    headers={
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("results", [])
        except Exception as e:
            logger.warning(f"[Exa] Search failed for '{query[:60]}': {e}")
            return []

    def format_results(self, query: str, results: list[dict[str, Any]]) -> str:
        """Format Exa results into a readable research block."""
        if not results:
            return f"Query: {query}\n- No results found."

        lines = [f"Query: {query}"]
        for r in results:
            title     = (r.get("title")         or "").strip()
            url       = (r.get("url")            or "").strip()
            summary   = (r.get("summary")        or "").strip()
            published = (r.get("publishedDate")  or "").strip()
            highlights = r.get("highlights") or []

            if title:
                lines.append(f"\n- {title}")
            if published:
                lines.append(f"  Published: {published[:10]}")
            if url:
                lines.append(f"  URL: {url}")
            if summary:
                lines.append(f"  Summary: {summary[:400]}")
            for h in highlights[:2]:
                if isinstance(h, str) and h.strip():
                    lines.append(f"  • {h.strip()[:200]}")

        return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Tinyfish search client
# Tinyfish is a web-search agent API (not a language model)
# Used for: broad current-events and prediction market queries
# Docs: https://tinyfish.ai
# ---------------------------------------------------------------------------

class TinyfishSearcher:
    """
    Wraps the Tinyfish web agent search API.
    Tinyfish is a web search agent — NOT a language model.
    It returns structured search results from the live web.
    Used alongside Exa for broader coverage and recency.
    """

    BASE_URL = "https://api.tinyfish.ai/v1"

    def __init__(
        self,
        api_key: str,
        max_results: int = 5,
        timeout_s: int = 30,
    ):
        self.api_key = api_key
        self.max_results = max_results
        self.timeout_s = timeout_s

    async def search(self, query: str) -> list[dict[str, Any]]:
        """
        Run a single Tinyfish search query.
        Returns list of result dicts with keys: title, url, content, score
        """
        if not self.api_key:
            logger.warning("[Tinyfish] No TINYFISH_API_KEY set — skipping search")
            return []

        payload = {
            "query": query,
            "max_results": self.max_results,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/search",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("results", [])
        except Exception as e:
            logger.warning(f"[Tinyfish] Search failed for '{query[:60]}': {e}")
            return []

    def format_results(self, query: str, results: list[dict[str, Any]]) -> str:
        """Format Tinyfish results into a readable research block."""
        if not results:
            return f"Query: {query}\n- No results found."

        lines = [f"Query: {query}"]
        for r in results:
            title   = (r.get("title")   or "").strip()
            url     = (r.get("url")     or "").strip()
            content = (r.get("content") or "").strip()

            if title:
                lines.append(f"\n- {title}")
            if url:
                lines.append(f"  URL: {url}")
            if content:
                lines.append(f"  Notes: {content[:300]}")

        return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Extremization
# ---------------------------------------------------------------------------

@dataclass
class ExtremizationConfig:
    """
    Logit-based extremization for OracleDeck forecasts.
    Pushes probabilities away from 0.5 when evidence is strong.

    Defaults (all env-overridable):
      factor : 1.45  — logit push strength
      floor  : 0.02  — minimum probability (avoids log-score blowup)
      ceil   : 0.98  — maximum probability
    """
    enabled: bool  = True
    factor:  float = 1.45
    floor:   float = 0.02
    ceil:    float = 0.98


def _logit(p: float) -> float:
    p = min(1.0 - 1e-12, max(1e-12, p))
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def extremize_probability(p: float, cfg: ExtremizationConfig) -> float:
    """Push probability away from 0.5 via logit scaling, then clamp."""
    if not cfg.enabled:
        return max(cfg.floor, min(cfg.ceil, p))
    x = _logit(p) * cfg.factor
    out = _sigmoid(x)
    return max(cfg.floor, min(cfg.ceil, out))


# ---------------------------------------------------------------------------
# Backend sync — posts forecast log to OracleDeck backend API
# ---------------------------------------------------------------------------

async def sync_to_backend(
    forecast_log: list[dict[str, Any]],
    backend_url: str,
    metaculus_token: str,
    duration_seconds: float,
    tournaments: list[str],
) -> None:
    """
    Post completed forecast batch to the OracleDeck backend API.
    Non-fatal — forecasts are already submitted to Metaculus.
    Failure here only means the dashboard won't update immediately.
    """
    if not backend_url:
        logger.info("[Backend] BACKEND_URL not set — skipping sync")
        return
    if not forecast_log:
        logger.info("[Backend] No forecasts to sync")
        return

    payload = {
        "forecasts": forecast_log,
        "run_metadata": {
            "ran_at": datetime.utcnow().isoformat() + "Z",
            "questions_processed": len(forecast_log),
            "duration_seconds": round(duration_seconds, 2),
            "tournaments": tournaments,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{backend_url}/api/forecasts/batch",
                headers={
                    "Authorization": f"Bearer {metaculus_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            logger.info(
                f"[Backend] Synced {len(forecast_log)} forecasts. "
                f"Status: {resp.status_code}"
            )
    except Exception as e:
        logger.warning(f"[Backend] Sync failed (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Main bot class — OracleDeck
# ---------------------------------------------------------------------------

class OracleDeck(ForecastBot):
    """
    OracleDeck — production superforecaster bot for Metaculus competitions.

    Targets:
      - Spring 2026 AI Forecasting Benchmark  (spring-aib-2026)
      - MiniBench bi-weekly tournament        (mini-bench)
      - Market Pulse Q1 2026                 (market-pulse-26q1)
      - Metaculus Cup                        (on demand)

    Research pipeline:
      1. Exa neural search      — semantic web search with highlights
      2. Tinyfish web agent     — broad current-events coverage
      3. LLM research summary   — Claude Sonnet 4.6 synthesises findings

    Forecast pipeline:
      1. Claude Sonnet 4.6      — deep superforecaster reasoning (default)
      2. GPT-5.4              — structured output parsing (parser)
      3. Logit extremization    — factor 1.45, floor 0.02, ceil 0.98

    Auth:
      METACULUS_TOKEN is used for both Metaculus API auth
      and OracleDeck backend Bearer token ingest auth.
    """

    _max_concurrent_questions          = 1
    _concurrency_limiter               = asyncio.Semaphore(1)
    _structure_output_validation_samples = 2

    _min_seconds_between_search_calls  = 1.2
    _min_seconds_between_llm_calls     = 0.35

    _last_search_call_ts: float = 0.0
    _last_llm_call_ts:    float = 0.0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        llms = kwargs.pop("llms", None)
        if llms is None:
            claude_llm = GeneralLlm(
                model=_CLAUDE_MODEL,
                temperature=0.15,
                timeout=60,
                allowed_tries=2,
            )
            gpt_llm = GeneralLlm(
                model=_GPT_MODEL,
                temperature=0.15,
                timeout=60,
                allowed_tries=2,
            )
            llms = {
                "default":    claude_llm,  # primary reasoning
                "summarizer": claude_llm,  # research summarisation
                "researcher": gpt_llm,     # query decomposition
                "parser":     gpt_llm,     # structured output parsing
            }
        super().__init__(*args, llms=llms, **kwargs)

        self._research_cache: dict[str, str] = {}

        # Exa — primary semantic search
        self._exa = ExaSearcher(
            api_key=EXA_API_KEY,
            num_results=5,
            highlight_sentences=3,
            timeout_s=30,
        )

        # Tinyfish — secondary broad web search agent
        self._tinyfish = TinyfishSearcher(
            api_key=TINYFISH_API_KEY,
            max_results=5,
            timeout_s=30,
        )

        # Extremization config
        self._ext_cfg = ExtremizationConfig(
            enabled=os.getenv("EXTREMIZE_ENABLED", "true").lower()
                    in ["1", "true", "yes", "y"],
            factor=float(os.getenv("EXTREMIZE_FACTOR", "1.45")),
            floor=float(os.getenv("EXTREMIZE_FLOOR",  "0.02")),
            ceil=float(os.getenv("EXTREMIZE_CEIL",    "0.98")),
        )

        # Forecast log — accumulated per run and synced to backend
        self._forecast_log: list[dict[str, Any]] = []
        self._run_start_ts: float = time.time()
        self._active_tournaments: list[str] = []

    # ------------------------------------------------------------------
    # Throttling
    # ------------------------------------------------------------------

    async def _throttle_search(self) -> None:
        now  = time.time()
        wait = (self._last_search_call_ts
                + self._min_seconds_between_search_calls) - now
        if wait > 0:
            await asyncio.sleep(wait + random.random() * 0.15)
        self._last_search_call_ts = time.time()

    async def _throttle_llm(self) -> None:
        now  = time.time()
        wait = (self._last_llm_call_ts
                + self._min_seconds_between_llm_calls) - now
        if wait > 0:
            await asyncio.sleep(wait + random.random() * 0.10)
        self._last_llm_call_ts = time.time()

    async def _llm_invoke(self, model_key: str, prompt: str) -> str:
        await self._throttle_llm()
        return await self.get_llm(model_key, "llm").invoke(prompt)

    # ------------------------------------------------------------------
    # Superforecasting heuristics preamble
    # ------------------------------------------------------------------

    @staticmethod
    def _superforecasting_preamble() -> str:
        return clean_indents(
            """
            ## Superforecasting Protocol — follow every step before giving a number

            **1. Reference class first (outside view)**
            Identify the broadest reference class this question belongs to.
            What fraction of similar past questions resolved YES (or at the
            predicted value)? Anchor your initial estimate to that base rate.

            **2. Inside view — case-specific evidence**
            Now consider what makes THIS case different from the reference class:
            - Causal drivers pushing toward YES / a higher value
            - Causal drivers pushing toward NO / a lower value
            - Key uncertainties or unknowns that could flip the outcome

            **3. Adjust for scope and time horizon**
            - Longer time horizons generally mean more regression to base rates.
            - Short horizons with strong status-quo momentum should reflect
              that inertia.

            **4. Check for cognitive biases**
            - Availability bias: Am I over-weighting vivid recent news?
            - Anchoring: Am I stuck on the first number I thought of?
            - Conjunction fallacy: Are my scenario chains too detailed?
            - Overconfidence: Is my interval wide enough?

            **5. Seek disconfirming evidence**
            What would most strongly argue AGAINST your current lean?
            Has that evidence been adequately weighted?

            **6. Synthesise: blend outside view + inside view**
            Start from the base rate, then adjust — usually by less than
            feels natural. Only move far from the base rate if you have
            strong, specific, reliable evidence.

            **7. Express calibrated confidence**
            - Near 50%: high genuine uncertainty, not laziness.
            - Near 5% or 95%: only if evidence is overwhelming AND base
              rate supports it.
            - Avoid round numbers unless the evidence truly warrants them.
            """
        ).strip()

    # ------------------------------------------------------------------
    # Research — Exa + Tinyfish dual search
    # ------------------------------------------------------------------

    async def _decompose_question(
        self, question: MetaculusQuestion
    ) -> list[str]:
        """
        Use GPT-5.4 to decompose the question into 3-5 targeted search queries.
        Covers: base rates, key drivers, timelines, prediction market odds.
        """
        prompt = clean_indents(
            f"""
            You are building a research plan for a superforecasting question.

            Return 3 to 5 web-search queries that would most improve a forecast
            for the question below. Queries should be short and specific, covering:
            base rates, key drivers, timelines/milestones, and prediction markets.

            Output ONLY a JSON array of strings. No preamble, no markdown.

            Question:
            {question.question_text}

            Resolution criteria:
            {question.resolution_criteria}

            Fine print:
            {question.fine_print}
            """
        )
        try:
            raw = await self._llm_invoke("researcher", prompt)
            raw = raw.strip()
            start = raw.find("[")
            end   = raw.rfind("]")
            if start != -1 and end != -1 and end > start:
                raw = raw[start: end + 1]
            queries = json.loads(raw)
            if isinstance(queries, list):
                return [
                    q.strip() for q in queries
                    if isinstance(q, str) and q.strip()
                ][:5]
        except Exception:
            pass
        return [
            f"{question.question_text} latest updates",
            f"{question.question_text} base rate historical frequency",
            f"{question.question_text} prediction market probability",
        ]

    async def _run_exa_searches(
        self, queries: list[str]
    ) -> list[str]:
        """
        Run all queries through Exa neural search.
        Returns list of formatted result blocks.
        """
        blocks: list[str] = []
        for query in queries:
            await self._throttle_search()
            results = await self._exa.search(query)
            block   = self._exa.format_results(query, results)
            if block.strip():
                blocks.append(block)
        return blocks

    async def _run_tinyfish_searches(
        self, queries: list[str]
    ) -> list[str]:
        """
        Run a subset of queries through Tinyfish web agent for broad coverage.
        Uses only the first 3 queries to avoid rate limits.
        Returns list of formatted result blocks.
        """
        blocks: list[str] = []
        for query in queries[:3]:
            await self._throttle_search()
            results = await self._tinyfish.search(query)
            block   = self._tinyfish.format_results(query, results)
            if block.strip():
                blocks.append(block)
        return blocks

    async def _dual_search_bundle(
        self, question: MetaculusQuestion
    ) -> str:
        """
        Run Exa + Tinyfish searches in parallel for a given question.
        Exa provides deep semantic results.
        Tinyfish provides broad current-events coverage.
        Results are merged into a single research bundle string.
        """
        queries = await self._decompose_question(question)

        # Add prediction market queries to Tinyfish pass
        market_queries = [
            f"metaforecast {question.question_text}",
            f"prediction market odds {question.question_text}",
        ]
        all_queries: list[str] = []
        for q in queries + market_queries:
            if q.strip() and q.strip() not in all_queries:
                all_queries.append(q.strip())

        # Run both search providers in parallel
        exa_blocks, tinyfish_blocks = await asyncio.gather(
            self._run_exa_searches(all_queries),
            self._run_tinyfish_searches(all_queries),
            return_exceptions=False,
        )

        sections: list[str] = []
        if exa_blocks:
            sections.append(
                "--- EXA NEURAL SEARCH RESULTS ---\n"
                + "\n\n".join(exa_blocks)
            )
        if tinyfish_blocks:
            sections.append(
                "--- TINYFISH WEB SEARCH RESULTS ---\n"
                + "\n\n".join(tinyfish_blocks)
            )

        return "\n\n".join(sections).strip()

    async def run_research(self, question: MetaculusQuestion) -> str:
        """
        Full research pipeline for a single question:
          1. Decompose question into search queries
          2. Run Exa + Tinyfish in parallel
          3. Summarise with Claude Sonnet 4.6
        Result is cached per question URL.
        """
        async with self._concurrency_limiter:
            if question.page_url in self._research_cache:
                return self._research_cache[question.page_url]

            base = clean_indents(
                f"""
                Question:
                {question.question_text}

                Resolution criteria:
                {question.resolution_criteria}

                Fine print:
                {question.fine_print}
                """
            ).strip()

            search_bundle = await self._dual_search_bundle(question)

            if search_bundle:
                raw_research = clean_indents(
                    f"""
                    {base}

                    {search_bundle}
                    """
                ).strip()
            else:
                raw_research = base

            summarize_prompt = clean_indents(
                f"""
                You are an assistant to a professional superforecaster.
                Summarize the most relevant evidence for forecasting the
                question below. Include: current status, key drivers,
                base rates if found, timelines/milestones, and any
                prediction market probabilities found.
                Be concise but information-dense. Max 600 words.

                {raw_research}
                """
            )

            try:
                summary = await self._llm_invoke(
                    "summarizer", summarize_prompt
                )
                if search_bundle:
                    final = clean_indents(
                        f"""
                        {base}

                        --- RESEARCH SUMMARY ---
                        {summary}

                        --- RAW SEARCH RESULTS ---
                        {search_bundle}
                        """
                    ).strip()
                else:
                    final = clean_indents(
                        f"""
                        {base}

                        --- RESEARCH SUMMARY ---
                        {summary}
                        """
                    ).strip()
            except Exception:
                final = raw_research

            self._research_cache[question.page_url] = final
            logger.info(
                f"[OracleDeck] Research complete for {question.page_url}"
            )
            return final

    # ------------------------------------------------------------------
    # Forecast log — records every forecast for backend sync
    # ------------------------------------------------------------------

    def _record_forecast(
        self,
        question: MetaculusQuestion,
        tournament: str,
        question_type: str,
        probability: float | None,
        reasoning: str,
        extremization_applied: bool,
    ) -> None:
        """Append a forecast record to the run log for backend sync."""
        self._forecast_log.append(
            {
                "question_id":            getattr(question, "id", None),
                "question_text":          question.question_text,
                "metaculus_url":          question.page_url,
                "tournament":             tournament,
                "question_type":          question_type,
                "probability":            probability,
                "reasoning_snippet":      reasoning[:500] if reasoning else "",
                "extremization_applied":  extremization_applied,
                "models_used":            [_CLAUDE_MODEL, _GPT_MODEL],
                "search_providers":       ["exa", "tinyfish"],
                "timestamp":              datetime.utcnow().isoformat() + "Z",
            }
        )

    # ------------------------------------------------------------------
    # Binary forecasts
    # ------------------------------------------------------------------

    async def _run_forecast_on_binary(
        self,
        question: BinaryQuestion,
        research: str,
    ) -> ReasonedPrediction[float]:
        prompt = clean_indents(
            f"""
            You are OracleDeck, a professional superforecaster.

            {self._superforecasting_preamble()}

            ---

            Question:
            {question.question_text}

            Background:
            {question.background_info}

            Resolution criteria (not yet satisfied):
            {question.resolution_criteria}

            {question.fine_print}

            Research:
            {research}

            Today is {datetime.now().strftime("%Y-%m-%d")}.

            Now reason step-by-step following the Superforecasting Protocol:
            (a) Reference class and base rate
            (b) Time left until resolution
            (c) Status quo outcome if nothing changes (outside view anchor)
            (d) Inside-view: key YES drivers
            (e) Inside-view: key NO drivers
            (f) Bias check — what am I most likely wrong about?
            (g) Final synthesis: blend outside + inside view

            Weight the status quo heavily unless there is strong specific
            evidence of change.
            {self._get_conditional_disclaimer_if_necessary(question)}

            End with: "Probability: ZZ%" (0-100)
            """
        )
        return await self._binary_prompt_to_forecast(question, prompt)

    async def _binary_prompt_to_forecast(
        self,
        question: BinaryQuestion,
        prompt: str,
    ) -> ReasonedPrediction[float]:
        reasoning = await self._llm_invoke("default", prompt)
        logger.info(
            f"[OracleDeck] Binary reasoning for {question.page_url}"
        )
        binary_prediction: BinaryPrediction = await structure_output(
            reasoning,
            BinaryPrediction,
            model=self.get_llm("parser", "llm"),
            num_validation_samples=self._structure_output_validation_samples,
        )
        raw_p = max(0.01, min(0.99, binary_prediction.prediction_in_decimal))
        extremized_p = extremize_probability(raw_p, self._ext_cfg)
        applied = abs(extremized_p - raw_p) > 0.001

        self._record_forecast(
            question=question,
            tournament=self._current_tournament,
            question_type="binary",
            probability=extremized_p,
            reasoning=reasoning,
            extremization_applied=applied,
        )
        return ReasonedPrediction(
            prediction_value=extremized_p, reasoning=reasoning
        )

    # ------------------------------------------------------------------
    # Multiple choice forecasts
    # ------------------------------------------------------------------

    async def _run_forecast_on_multiple_choice(
        self,
        question: MultipleChoiceQuestion,
        research: str,
    ) -> ReasonedPrediction[PredictedOptionList]:
        prompt = clean_indents(
            f"""
            You are OracleDeck, a professional superforecaster.

            {self._superforecasting_preamble()}

            ---

            Question:
            {question.question_text}

            Options: {question.options}

            Background:
            {question.background_info}

            Resolution criteria:
            {question.resolution_criteria}

            {question.fine_print}

            Research:
            {research}

            Today is {datetime.now().strftime("%Y-%m-%d")}.

            Now reason step-by-step following the Superforecasting Protocol:
            (a) Reference class: historically how often does each option type
                win in similar questions?
            (b) Time left until resolution
            (c) Status quo anchor: which option does current trajectory favour?
            (d) Inside-view drivers that could shift away from status quo option
            (e) Plausible surprise outcome — why it should not be zero
            (f) Bias check — am I clustering too much probability on one option?

            {self._get_conditional_disclaimer_if_necessary(question)}
            Avoid assigning 0% to any option unless logically impossible.

            End with probabilities in this exact order {question.options}:
            Option_A: Probability_A
            ...
            """
        )
        return await self._multiple_choice_prompt_to_forecast(
            question, prompt
        )

    async def _multiple_choice_prompt_to_forecast(
        self,
        question: MultipleChoiceQuestion,
        prompt: str,
    ) -> ReasonedPrediction[PredictedOptionList]:
        parsing_instructions = clean_indents(
            f"""
            Option names must match one of:
            {question.options}
            Do not drop any option, even if 0%.
            """
        )
        reasoning = await self._llm_invoke("default", prompt)
        logger.info(
            f"[OracleDeck] MC reasoning for {question.page_url}"
        )
        predicted_option_list: PredictedOptionList = await structure_output(
            text_to_structure=reasoning,
            output_type=PredictedOptionList,
            model=self.get_llm("parser", "llm"),
            num_validation_samples=self._structure_output_validation_samples,
            additional_instructions=parsing_instructions,
        )
        self._record_forecast(
            question=question,
            tournament=self._current_tournament,
            question_type="multiple_choice",
            probability=None,
            reasoning=reasoning,
            extremization_applied=False,
        )
        return ReasonedPrediction(
            prediction_value=predicted_option_list, reasoning=reasoning
        )

    # ------------------------------------------------------------------
    # Numeric forecasts
    # ------------------------------------------------------------------

    async def _run_forecast_on_numeric(
        self,
        question: NumericQuestion,
        research: str,
    ) -> ReasonedPrediction[NumericDistribution]:
        upper_bound_message, lower_bound_message = (
            self._create_upper_and_lower_bound_messages(question)
        )
        prompt = clean_indents(
            f"""
            You are OracleDeck, a professional superforecaster.

            {self._superforecasting_preamble()}

            ---

            Question:
            {question.question_text}

            Background:
            {question.background_info}

            {question.resolution_criteria}

            {question.fine_print}

            Units: {question.unit_of_measure if question.unit_of_measure else "Not stated (infer)"}

            Research:
            {research}

            Today is {datetime.now().strftime("%Y-%m-%d")}.

            {lower_bound_message}
            {upper_bound_message}

            Formatting:
            - No scientific notation
            - Percentiles must be strictly increasing

            Now reason step-by-step following the Superforecasting Protocol:
            (a) Reference class and historical base rate for this quantity
            (b) Time left until resolution
            (c) Status quo / trend-continuation anchor (outside view)
            (d) Factors that could push the value higher than the trend
            (e) Factors that could push the value lower than the trend
            (f) Expert or market expectations found in research
            (g) Tail scenarios: extreme low and extreme high
            (h) Bias check — are my intervals too narrow?

            {self._get_conditional_disclaimer_if_necessary(question)}
            Use wide 90/10 intervals to reflect genuine uncertainty.

            End with:
            Percentile 10: XX
            Percentile 20: XX
            Percentile 40: XX
            Percentile 60: XX
            Percentile 80: XX
            Percentile 90: XX
            """
        )
        return await self._numeric_prompt_to_forecast(question, prompt)

    async def _numeric_prompt_to_forecast(
        self,
        question: NumericQuestion,
        prompt: str,
    ) -> ReasonedPrediction[NumericDistribution]:
        reasoning = await self._llm_invoke("default", prompt)
        logger.info(
            f"[OracleDeck] Numeric reasoning for {question.page_url}"
        )
        parsing_instructions = clean_indents(
            f"""
            Parse a numeric percentile forecast for:
            "{question.question_text}"
            Units: {question.unit_of_measure}
            Convert units if needed.
            If percentiles are missing, indicate not explicitly given.
            """
        )
        percentile_list: list[Percentile] = await structure_output(
            reasoning,
            list[Percentile],
            model=self.get_llm("parser", "llm"),
            additional_instructions=parsing_instructions,
            num_validation_samples=self._structure_output_validation_samples,
        )
        prediction = NumericDistribution.from_question(
            percentile_list, question
        )
        self._record_forecast(
            question=question,
            tournament=self._current_tournament,
            question_type="numeric",
            probability=None,
            reasoning=reasoning,
            extremization_applied=False,
        )
        return ReasonedPrediction(
            prediction_value=prediction, reasoning=reasoning
        )

    # ------------------------------------------------------------------
    # Date forecasts
    # ------------------------------------------------------------------

    async def _run_forecast_on_date(
        self,
        question: DateQuestion,
        research: str,
    ) -> ReasonedPrediction[NumericDistribution]:
        upper_bound_message, lower_bound_message = (
            self._create_upper_and_lower_bound_messages(question)
        )
        prompt = clean_indents(
            f"""
            You are OracleDeck, a professional superforecaster.

            {self._superforecasting_preamble()}

            ---

            Question:
            {question.question_text}

            Background:
            {question.background_info}

            {question.resolution_criteria}

            {question.fine_print}

            Research:
            {research}

            Today is {datetime.now().strftime("%Y-%m-%d")}.

            {lower_bound_message}
            {upper_bound_message}

            Formatting:
            - Dates must be YYYY-MM-DD
            - Percentiles must be chronological and strictly increasing

            Now reason step-by-step following the Superforecasting Protocol:
            (a) Reference class: how long do similar processes historically take?
            (b) Time already elapsed and current pace (outside view anchor)
            (c) Status quo / trend-continuation scenario
            (d) Factors that could accelerate the timeline
            (e) Factors that could delay the timeline
            (f) Expert or market expectations on timing
            (g) Tail scenarios: unusually early and unusually late
            (h) Bias check — am I anchoring too tightly to one date?

            {self._get_conditional_disclaimer_if_necessary(question)}
            Use wide 90/10 intervals to reflect genuine timing uncertainty.

            End with:
            Percentile 10: YYYY-MM-DD
            Percentile 20: YYYY-MM-DD
            Percentile 40: YYYY-MM-DD
            Percentile 60: YYYY-MM-DD
            Percentile 80: YYYY-MM-DD
            Percentile 90: YYYY-MM-DD
            """
        )
        return await self._date_prompt_to_forecast(question, prompt)

    async def _date_prompt_to_forecast(
        self,
        question: DateQuestion,
        prompt: str,
    ) -> ReasonedPrediction[NumericDistribution]:
        reasoning = await self._llm_invoke("default", prompt)
        logger.info(
            f"[OracleDeck] Date reasoning for {question.page_url}"
        )
        parsing_instructions = clean_indents(
            f"""
            Parse a date percentile forecast for:
            "{question.question_text}"
            If a percentile has no time, assume midnight UTC.
            If percentiles are missing, indicate not explicitly given.
            """
        )
        date_percentile_list: list[DatePercentile] = await structure_output(
            reasoning,
            list[DatePercentile],
            model=self.get_llm("parser", "llm"),
            additional_instructions=parsing_instructions,
            num_validation_samples=self._structure_output_validation_samples,
        )
        percentile_list = [
            Percentile(
                percentile=dp.percentile,
                value=dp.value.timestamp(),
            )
            for dp in date_percentile_list
        ]
        prediction = NumericDistribution.from_question(
            percentile_list, question
        )
        self._record_forecast(
            question=question,
            tournament=self._current_tournament,
            question_type="date",
            probability=None,
            reasoning=reasoning,
            extremization_applied=False,
        )
        return ReasonedPrediction(
            prediction_value=prediction, reasoning=reasoning
        )

    # ------------------------------------------------------------------
    # Bound helpers
    # ------------------------------------------------------------------

    def _create_upper_and_lower_bound_messages(
        self,
        question: NumericQuestion | DateQuestion,
    ) -> tuple[str, str]:
        if isinstance(question, NumericQuestion):
            upper = (
                question.nominal_upper_bound
                if question.nominal_upper_bound is not None
                else question.upper_bound
            )
            lower = (
                question.nominal_lower_bound
                if question.nominal_lower_bound is not None
                else question.lower_bound
            )
            unit = question.unit_of_measure
        elif isinstance(question, DateQuestion):
            upper = question.upper_bound.date().isoformat()
            lower = question.lower_bound.date().isoformat()
            unit  = ""
        else:
            raise ValueError(f"Unsupported question type: {type(question)}")

        upper_msg = (
            f"The question creator thinks the number is likely not higher "
            f"than {upper} {unit}."
            if question.open_upper_bound
            else f"The outcome can not be higher than {upper} {unit}."
        )
        lower_msg = (
            f"The question creator thinks the number is likely not lower "
            f"than {lower} {unit}."
            if question.open_lower_bound
            else f"The outcome can not be lower than {lower} {unit}."
        )
        return upper_msg, lower_msg

    # ------------------------------------------------------------------
    # Conditional forecasts
    # ------------------------------------------------------------------

    async def _run_forecast_on_conditional(
        self,
        question: ConditionalQuestion,
        research: str,
    ) -> ReasonedPrediction[ConditionalPrediction]:
        parent_info, full_research = await self._get_question_prediction_info(
            question.parent, research, "parent"
        )
        child_info, full_research = await self._get_question_prediction_info(
            question.child, full_research, "child"
        )
        yes_info, full_research = await self._get_question_prediction_info(
            question.question_yes, full_research, "yes"
        )
        no_info, full_research = await self._get_question_prediction_info(
            question.question_no, full_research, "no"
        )

        for info in [parent_info, child_info, yes_info, no_info]:
            pv = getattr(info, "prediction_value", None)
            if isinstance(pv, float):
                info.prediction_value = extremize_probability(  # type: ignore[attr-defined]
                    pv, self._ext_cfg
                )

        full_reasoning = clean_indents(
            f"""
            ## Parent Question Reasoning
            {parent_info.reasoning}
            ## Child Question Reasoning
            {child_info.reasoning}
            ## Yes Question Reasoning
            {yes_info.reasoning}
            ## No Question Reasoning
            {no_info.reasoning}
            """
        ).strip()

        full_prediction = ConditionalPrediction(
            parent=parent_info.prediction_value,          # type: ignore
            child=child_info.prediction_value,            # type: ignore
            prediction_yes=yes_info.prediction_value,     # type: ignore
            prediction_no=no_info.prediction_value,       # type: ignore
        )
        return ReasonedPrediction(
            reasoning=full_reasoning,
            prediction_value=full_prediction,
        )

    async def _get_question_prediction_info(
        self,
        question: MetaculusQuestion,
        research: str,
        question_type: str,
    ) -> tuple[
        ReasonedPrediction[PredictionTypes | PredictionAffirmed], str
    ]:
        from forecasting_tools.data_models.data_organizer import DataOrganizer

        previous_forecasts = question.previous_forecasts
        if (
            question_type in ["parent", "child"]
            and previous_forecasts
            and question_type not in self.force_reforecast_in_conditional
        ):
            previous_forecast = previous_forecasts[-1]
            current_utc_time  = datetime.now(timezone.utc)
            if (
                previous_forecast.timestamp_end is None
                or previous_forecast.timestamp_end > current_utc_time
            ):
                pretty_value = DataOrganizer.get_readable_prediction(
                    previous_forecast
                )
                prediction = ReasonedPrediction(
                    prediction_value=PredictionAffirmed(),
                    reasoning=(
                        f"Already existing forecast reaffirmed "
                        f"at {pretty_value}."
                    ),
                )
                return (prediction, research)  # type: ignore
        info = await self._make_prediction(question, research)
        full_research = self._add_reasoning_to_research(
            research, info, question_type
        )
        return info, full_research  # type: ignore

    def _add_reasoning_to_research(
        self,
        research: str,
        reasoning: ReasonedPrediction[PredictionTypes],
        question_type: str,
    ) -> str:
        from forecasting_tools.data_models.data_organizer import DataOrganizer

        question_type = question_type.title()
        return clean_indents(
            f"""
            {research}
            ---
            ## {question_type} Question Information
            Previously forecasted to:
            {DataOrganizer.get_readable_prediction(reasoning.prediction_value)}
            Reasoning:
            ```
            {reasoning.reasoning}
            ```
            Do NOT use this to re-forecast the {question_type} question.
            """
        ).strip()

    def _get_conditional_disclaimer_if_necessary(
        self, question: MetaculusQuestion
    ) -> str:
        if question.conditional_type not in ["yes", "no"]:
            return ""
        return clean_indents(
            """
            You are given a conditional question with a parent and child.
            Forecast ONLY the CHILD question given the parent's resolution.
            Do not re-forecast the parent.
            """
        ).strip()

    # ------------------------------------------------------------------
    # Extremization sweep on tournament results
    # ------------------------------------------------------------------

    def _extremize_report_if_binary(self, report: Any) -> None:
        try:
            pv = getattr(report, "prediction_value", None)
            if isinstance(pv, float):
                setattr(
                    report,
                    "prediction_value",
                    extremize_probability(pv, self._ext_cfg),
                )
            pred = getattr(report, "prediction", None)
            if isinstance(pred, float):
                setattr(
                    report,
                    "prediction",
                    extremize_probability(pred, self._ext_cfg),
                )
        except Exception:
            return

    def _extremize_reports(self, forecast_reports: list[Any]) -> list[Any]:
        for r in forecast_reports:
            self._extremize_report_if_binary(r)
        return forecast_reports

    # ------------------------------------------------------------------
    # Tournament overrides — track active tournament + post-run sync
    # ------------------------------------------------------------------

    @property
    def _current_tournament(self) -> str:
        return (
            self._active_tournaments[-1]
            if self._active_tournaments
            else "unknown"
        )

    async def forecast_on_tournament(
        self, tournament_id: str | int, *args: Any, **kwargs: Any
    ) -> list[Any]:
        self._active_tournaments.append(str(tournament_id))
        try:
            reports = await super().forecast_on_tournament(
                tournament_id, *args, **kwargs
            )
        finally:
            if self._active_tournaments:
                self._active_tournaments.pop()

        if isinstance(reports, list):
            return self._extremize_reports(reports)
        return reports

    async def forecast_questions(
        self, *args: Any, **kwargs: Any
    ) -> list[Any]:
        reports = await super().forecast_questions(*args, **kwargs)
        if isinstance(reports, list):
            return self._extremize_reports(reports)
        return reports

    # ------------------------------------------------------------------
    # Backend sync — called after all tournaments complete
    # ------------------------------------------------------------------

    async def sync_forecasts_to_backend(self) -> None:
        """
        Post all forecasts from this run to the OracleDeck backend API.
        Triggered automatically after all tournaments complete.
        Uses METACULUS_TOKEN as the shared Bearer auth secret.
        """
        duration = time.time() - self._run_start_ts
        await sync_to_backend(
            forecast_log=self._forecast_log,
            backend_url=BACKEND_URL,
            metaculus_token=METACULUS_TOKEN,
            duration_seconds=duration,
            tournaments=list(
                dict.fromkeys(
                    r.get("tournament", "unknown")
                    for r in self._forecast_log
                )
            ),
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("LiteLLM").propagate = False

    parser = argparse.ArgumentParser(
        description="Run OracleDeck — the superforecaster bot"
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["tournament", "metaculus_cup", "test_questions"],
        default="tournament",
    )
    args = parser.parse_args()
    run_mode: Literal[
        "tournament", "metaculus_cup", "test_questions"
    ] = args.mode

    bot = OracleDeck(
        research_reports_per_question=1,
        predictions_per_research_report=3,
        use_research_summary_to_forecast=False,
        publish_reports_to_metaculus=True,
        folder_to_save_reports_to=None,
        skip_previously_forecasted_questions=True,
        extra_metadata_in_explanation=True,
    )

    client = MetaculusClient()

    if run_mode == "tournament":
        spring_aib_reports = asyncio.run(
            bot.forecast_on_tournament(
                client.CURRENT_AI_COMPETITION_ID,
                return_exceptions=True,
            )
        )
        minibench_reports = asyncio.run(
            bot.forecast_on_tournament(
                client.CURRENT_MINIBENCH_ID,
                return_exceptions=True,
            )
        )
        market_pulse_reports = asyncio.run(
            bot.forecast_on_tournament(
                "market-pulse-26q1",
                return_exceptions=True,
            )
        )
        forecast_reports = (
            spring_aib_reports
            + minibench_reports
            + market_pulse_reports
        )

    elif run_mode == "metaculus_cup":
        bot.skip_previously_forecasted_questions = False
        forecast_reports = asyncio.run(
            bot.forecast_on_tournament(
                client.CURRENT_METACULUS_CUP_ID,
                return_exceptions=True,
            )
        )

    elif run_mode == "test_questions":
        EXAMPLE_QUESTIONS = [
            "https://www.metaculus.com/questions/578/human-extinction-by-2100/",
            "https://www.metaculus.com/questions/14333/age-of-oldest-human-as-of-2100/",
            "https://www.metaculus.com/questions/22427/number-of-new-leading-ai-labs/",
            "https://www.metaculus.com/c/diffusion-community/38880/how-many-us-labor-strikes-due-to-ai-in-2029/",
        ]
        bot.skip_previously_forecasted_questions = False
        questions = [
            client.get_question_by_url(url)
            for url in EXAMPLE_QUESTIONS
        ]
        forecast_reports = asyncio.run(
            bot.forecast_questions(
                questions, return_exceptions=True
            )
        )

    bot.log_report_summary(forecast_reports)

    # Sync all forecasts to OracleDeck backend dashboard
    asyncio.run(bot.sync_forecasts_to_backend())
