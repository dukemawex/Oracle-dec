#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
import re
import json
from dataclasses import dataclass
from datetime import datetime, timezone, date
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Literal

import numpy as np
import dotenv
from pydantic import BaseModel, Field

from forecasting_tools import (
    BinaryQuestion,
    ForecastBot,
    GeneralLlm,
    MetaculusClient,
    MetaculusQuestion,
    MultipleChoiceQuestion,
    NumericDistribution,
    NumericQuestion,
    Percentile,
    BinaryPrediction,
    PredictedOptionList,
    ReasonedPrediction,
    clean_indents,
    structure_output,
)

dotenv.load_dotenv()
logger = logging.getLogger(__name__)

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Spring Tournament ID — update if Metaculus changes the slug/ID for the
# current Spring Tournament season.
# ---------------------------------------------------------------------------
SPRING_TOURNAMENT_ID = "spring-forecasting-tournament-2025"


def sanitize_llm_json(text: str) -> str:
    text = re.sub(r"(?<=\d)_(?=\d)", "", text)

    def clean_num(match):
        val = match.group(2)
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", val)
        return f"\"{match.group(1)}\": {nums[0]}" if nums else match.group(0)

    text = re.sub(
        r"\"(value|percentile|probability|prediction_in_decimal|revised_prediction_in_decimal|multiplier|delta)\":\s*\"([^\"]+)\"",
        clean_num,
        text,
    )

    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def safe_model(model_cls: type[BaseModel], data: Any) -> BaseModel:
    try:
        if isinstance(data, model_cls):
            return data
        if isinstance(data, (str, bytes)):
            s = data.decode() if isinstance(data, bytes) else data
            clean_data = sanitize_llm_json(s)
            return model_cls.model_validate_json(clean_data)
        if isinstance(data, dict):
            return model_cls.model_validate(data)
        return model_cls(**data)
    except Exception as e:
        logger.error(f"MODEL INSTANTIATION FAILED for {model_cls.__name__}: {e}")
        raise


class RawPercentile(BaseModel):
    percentile: float
    value: float




class ForecastingPrinciples:
    @staticmethod
    def get_generic_base_rate() -> str:
        return (
            "BASE RATE: In the absence of strong evidence, default to historical frequencies "
            "or uniform priors where applicable. Most novel events have low base rates."
        )

    @staticmethod
    def get_generic_fermi_prompt() -> str:
        return (
            "FERMI GUIDANCE:\n"
            "1) Define the target quantity precisely.\n"
            "2) Decompose into drivers/factors.\n"
            "3) Estimate each factor using available evidence.\n"
            "4) Combine factors algebraically.\n"
            "5) Quantify uncertainty; keep intervals wide unless evidence is strong."
        )

    @staticmethod
    def apply_time_decay(prob: float, close_time: Optional[datetime]) -> float:
        if close_time is None:
            return prob
        now = datetime.now(timezone.utc)
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        days = max(0.0, (close_time - now).total_seconds() / 86400.0)
        if days > 365:
            return 0.3 * prob + 0.7 * 0.5
        if days > 180:
            return 0.5 * prob + 0.5 * 0.5
        if days > 90:
            return 0.7 * prob + 0.3 * 0.5
        return prob

    @staticmethod
    def logit(p: float) -> float:
        p = float(np.clip(p, 1e-6, 1 - 1e-6))
        return float(np.log(p / (1 - p)))

    @staticmethod
    def sigmoid(x: float) -> float:
        return float(1 / (1 + np.exp(-x)))

    @classmethod
    def extremize_logit(cls, p: float, strength: float) -> float:
        strength = float(np.clip(strength, 0.5, 3.0))
        return float(np.clip(cls.sigmoid(strength * cls.logit(p)), 0.0, 1.0))


class DecompositionOutput(BaseModel):
    subquestions: List[str] = Field(default_factory=list)
    key_entities: List[str] = Field(default_factory=list)
    key_metrics: List[str] = Field(default_factory=list)


class NumericRegime(str, Enum):
    LOOKUP = "lookup"
    PARTIAL_REVEAL_SUM = "partial_reveal_sum"
    STRUCTURED_TS = "structured_ts"
    GENERIC = "generic"


class PartialRevealExtract(BaseModel):
    known_subtotal: Optional[float] = None
    known_parts: Optional[int] = Field(default=None, ge=0)
    total_parts: Optional[int] = Field(default=None, ge=1)
    notes: Optional[str] = None


class ReferenceClassExtract(BaseModel):
    reference_totals: List[float] = Field(default_factory=list)
    trend_multiplier: Optional[float] = None
    notes: Optional[str] = None


class LevelSeriesExtract(BaseModel):
    current_value: Optional[float] = None
    current_date: Optional[str] = None
    recent_values: List[float] = Field(default_factory=list)
    notes: Optional[str] = None


class BoundedMultiplier(BaseModel):
    multiplier: float


class BoundedDelta(BaseModel):
    delta: float


@dataclass
class BotFeatureFlags:
    enable_extremize: bool = True
    enable_decomposition: bool = True
    enable_numeric_regimes: bool = True


class OracleDeckV1(ForecastBot):
    """
    OracleDeck v1 — Spring Tournament forecasting bot.

    Research providers : Sonar Small 128k online + Mistral Small 3.1 24B online (parallel gatherers) → Mistral 7B (auditor). No external API keys required.
    Forecasting models : Llama 3.3 70B (judge/critic/decomposer) + Mistral 7B (red-team/auditor)
                         + Sonar Small (query optimisation) + Llama 3.1 8B (parser).
                         All free-tier via OpenRouter.
    Extremize         : enabled by default (≥60 / ≤40 gate, logit method).
    Target            : Spring Tournament + Mini Bench.
    """

    _structure_output_validation_samples = 1

    def __init__(
        self,
        *args,
        bot_name: str = "oracledeckv1",
        flags: Optional[BotFeatureFlags] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.bot_name = bot_name
        self.flags = flags or BotFeatureFlags()


        self._recent_predictions: list[tuple[MetaculusQuestion, float]] = []

    def _llm_config_defaults(self) -> Dict[str, str]:
        # Free-tier models only (confirmed $0/M on OpenRouter as of April 2026).
        # Role mapping:
        #   query_optimizer  → Sonar Small 128k     (live web retrieval — gatherer 1)
        #   mistral_online   → Mistral Small 3.1 24B (live web retrieval — gatherer 2)
        #   red_team/auditor → Mistral 7B            (skeptical critique / auditor)
        #   judge/critic     → Llama 3.3 70B         (strongest free reasoner)
        #   parser/summarizer→ Llama 3.1 8B          (lightweight structured output)
        #   decomposer       → Llama 3.3 70B         (needs broad reasoning)
        return {
            "default":         "openrouter/meta-llama/llama-3.3-70b-instruct:free",
            "parser":          "openrouter/meta-llama/llama-3.1-8b-instruct:free",
            "summarizer":      "openrouter/meta-llama/llama-3.1-8b-instruct:free",
            "query_optimizer": "openrouter/perplexity/llama-3.1-sonar-small-128k-online",
            "mistral_online":  "openrouter/mistralai/mistral-small-3.1-24b-instruct:free",
            "critic":          "openrouter/meta-llama/llama-3.3-70b-instruct:free",
            "red_team":        "openrouter/mistralai/mistral-7b-instruct:free",
            "decomposer":      "openrouter/meta-llama/llama-3.3-70b-instruct:free",
        }

    # ------------------------------------------------------------------
    # Research helpers
    # ------------------------------------------------------------------

    def _ensure_some_research_or_raise(self, research: str) -> None:
        if not research or "[RESEARCH FAILED]" in research:
            raise RuntimeError("Research pipeline returned no usable content.")

    def _research_quality_weight(self, research: str) -> float:
        # Dual gatherers + auditor → highest quality
        both_gatherers = "### GATHERER 1" in research and "### GATHERER 2" in research
        has_audit      = "### RISK AUDIT" in research
        if both_gatherers and has_audit:
            return 0.90
        if both_gatherers or ("### BASE CASE" in research and has_audit):
            return 0.75
        if "### BASE CASE" in research or both_gatherers:
            return 0.55
        return 0.35

    # ------------------------------------------------------------------
    # Decomposition + query optimisation
    # ------------------------------------------------------------------

    async def _decompose_question(self, question: MetaculusQuestion) -> Optional[DecompositionOutput]:
        if not self.flags.enable_decomposition:
            return None
        try:
            llm = self.get_llm("decomposer", "llm")
            prompt = clean_indents(
                f"""
Decompose the following forecasting question into:
- 3-6 subquestions that would help research it
- key entities (people, orgs, products, locations)
- key metrics (numbers or quantities to track)

Return ONLY JSON with keys:
{{"subquestions":[...], "key_entities":[...], "key_metrics":[...]}}

Question:
{question.question_text}

Resolution criteria:
{question.resolution_criteria}
"""
            )
            raw = await llm.invoke(prompt)
            return safe_model(DecompositionOutput, sanitize_llm_json(raw))  # type: ignore[return-value]
        except Exception as e:
            logger.warning(f"Question decomposition failed: {e}")
            return None

    async def run_research(self, question: MetaculusQuestion) -> str:
        """
        Three-stage free-model research pipeline.

        Stage 1a — Gatherer 1 (Sonar Small 128k online):
            Live web retrieval focused on latest data and base rates.

        Stage 1b — Gatherer 2 (Mistral Small 3.1 24B online) — parallel:
            Independent live retrieval pass for cross-verification and
            coverage of sources the first gatherer may have missed.

        Stage 2 — Auditor (Mistral 7B):
            Receives merged output from both gatherers. Flags date/scope
            conflicts, states YES-resolution direction, lists 3 domain-
            specific long-tail risks, rates forecast difficulty.
        """
        gatherer1_llm = self.get_llm("query_optimizer", "llm")  # Sonar Small 128k online
        gatherer2_llm = self.get_llm("mistral_online", "llm")   # Mistral Small 3.1 24B online
        auditor_llm   = self.get_llm("red_team", "llm")          # Mistral 7B — auditor

        gatherer_prompt = (
            f"Search for the latest 2026 data on: {question.question_text}\n\n"
            f"RESOLUTION CRITERIA: {question.resolution_criteria}\n\n"
            f"{ForecastingPrinciples.get_generic_base_rate()}\n\n"
            f"CRITICAL: If specific recent data is unavailable, you MUST find the "
            f"historical base rate (frequency of occurrence) for similar events "
            f"over the last 20 years. Never return an empty report."
        )

        # Both gatherers run in parallel
        g1_result, g2_result = await asyncio.gather(
            gatherer1_llm.invoke(gatherer_prompt),
            gatherer2_llm.invoke(gatherer_prompt),
            return_exceptions=True,
        )

        if isinstance(g1_result, Exception):
            logger.error(f"Gatherer 1 (Sonar) failed: {g1_result}")
            g1_result = "[Gatherer 1 failed]"
        if isinstance(g2_result, Exception):
            logger.error(f"Gatherer 2 (Mistral online) failed: {g2_result}")
            g2_result = "[Gatherer 2 failed]"

        merged_research = (
            f"### GATHERER 1 (Sonar Small online)\n{g1_result}\n\n"
            f"### GATHERER 2 (Mistral Small 3.1 online)\n{g2_result}"
        )

        auditor_prompt = (
            f"You are a skeptical analyst reviewing forecasting research.\n\n"
            f"QUESTION: {question.question_text}\n"
            f"RESOLUTION CRITERIA: {question.resolution_criteria}\n\n"
            f"RESEARCH TO AUDIT (two independent retrieval passes):\n{merged_research}\n\n"
            f"YOUR TASKS:\n"
            f"1. Identify any date or scope conflicts between the research and the "
            f"   resolution criteria.\n"
            f"2. Note any meaningful disagreements between the two gatherers.\n"
            f"3. State whether the question resolves YES on a *positive* or *negative* "
            f"   outcome (e.g. 'YES = event occurs' vs 'YES = event averted').\n"
            f"4. List exactly 3 long-tail risks *specific to this question* that could "
            f"   cause a well-reasoned forecast to fail. Be concrete, not generic.\n"
            f"5. Rate overall forecast difficulty: LOW / MEDIUM / HIGH."
        )
        try:
            audit_results = await auditor_llm.invoke(auditor_prompt)
        except Exception as e:
            logger.warning(f"Auditor failed: {e}")
            audit_results = "[Auditor unavailable]"

        research = (
            f"{ForecastingPrinciples.get_generic_fermi_prompt()}\n\n"
            f"### BASE CASE (dual gatherers)\n{merged_research}\n\n"
            f"### RISK AUDIT (Auditor — Mistral 7B)\n{audit_results}"
        )

        self._ensure_some_research_or_raise(research)
        return research

    # ------------------------------------------------------------------
    # Numeric helpers
    # ------------------------------------------------------------------

    def _create_upper_and_lower_bound_messages(self, question: NumericQuestion) -> Tuple[str, str]:
        upper = question.nominal_upper_bound if question.nominal_upper_bound is not None else question.upper_bound
        lower = question.nominal_lower_bound if question.nominal_lower_bound is not None else question.lower_bound
        unit = question.unit_of_measure or ""
        upper_msg = (
            f"The question creator thinks the number is likely not higher than {upper} {unit}."
            if getattr(question, "open_upper_bound", False)
            else f"The outcome can not be higher than {upper} {unit}."
        )
        lower_msg = (
            f"The question creator thinks the number is likely not lower than {lower} {unit}."
            if getattr(question, "open_lower_bound", False)
            else f"The outcome can not be lower than {lower} {unit}."
        )
        return upper_msg, lower_msg

    def _numeric_parsing_instructions(self, question: NumericQuestion) -> str:
        return clean_indents(
            f"""
Extract a numeric forecast distribution from the text.

Output MUST be a list of objects with fields:
  - percentile
  - value

Percentile can be:
  - 10,20,40,60,80,90
  OR
  - 0.1,0.2,0.4,0.6,0.8,0.9

Values:
  - MUST be in units: {question.unit_of_measure}
  - Never use scientific notation.

Rules:
  - Required percentiles are exactly those six.
  - Values must be strictly increasing with percentile.
"""
        )

    @staticmethod
    def _extract_percentile_block(text: str) -> str:
        m = re.search(
            r"(Percentile\s*10\s*:.*?Percentile\s*90\s*:.*?)(?:\n\s*\n|$)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if m:
            return m.group(1).strip()
        lines = []
        for line in text.splitlines():
            if re.search(r"^\s*Percentile\s*(10|20|40|60|80|90)\s*:", line, flags=re.IGNORECASE):
                lines.append(line.strip())
        return "\n".join(lines).strip()

    @staticmethod
    def _normalize_raw_percentiles(raw: List[RawPercentile]) -> List[Percentile]:
        out: List[Percentile] = []
        for rp in raw:
            p = float(rp.percentile)
            if p > 1.0:
                p = p / 100.0
            p = max(0.0, min(1.0, p))
            out.append(Percentile(percentile=p, value=float(rp.value)))
        return out

    @staticmethod
    def _require_standard_percentiles(pcts: List[Percentile]) -> List[Percentile]:
        required = [0.1, 0.2, 0.4, 0.6, 0.8, 0.9]
        by = {round(float(p.percentile), 3): p for p in pcts}
        missing = [r for r in required if round(r, 3) not in by]
        if missing:
            return []
        return [by[round(r, 3)] for r in required]

    @staticmethod
    def _enforce_monotone(pcts: List[Percentile]) -> List[Percentile]:
        pcts = sorted(pcts, key=lambda x: float(x.percentile))
        for i in range(1, len(pcts)):
            if pcts[i].value <= pcts[i - 1].value:
                pcts[i].value = pcts[i - 1].value + 1e-6
        return pcts

    @staticmethod
    def _bounds_fallback(question: NumericQuestion) -> List[Percentile]:
        lo = float(question.lower_bound)
        hi = float(question.upper_bound)
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            lo, hi = 0.0, 1.0
        w = {0.1: 0.05, 0.2: 0.15, 0.4: 0.40, 0.6: 0.60, 0.8: 0.85, 0.9: 0.95}
        pcts = [Percentile(percentile=p, value=lo + (hi - lo) * w[p]) for p in [0.1, 0.2, 0.4, 0.6, 0.8, 0.9]]
        return OracleDeckV1._enforce_monotone(pcts)

    @staticmethod
    def _median_from_40_60(pcts: List[Percentile]) -> float:
        by = {round(float(p.percentile), 3): float(p.value) for p in pcts}
        if 0.4 in by and 0.6 in by:
            return 0.5 * (by[0.4] + by[0.6])
        return float(sorted(pcts, key=lambda x: x.percentile)[len(pcts) // 2].value) if pcts else 0.0

    @staticmethod
    def _p10_p90(pcts: List[Percentile]) -> Tuple[Optional[float], Optional[float]]:
        by = {round(float(p.percentile), 3): float(p.value) for p in pcts}
        return by.get(0.1), by.get(0.9)

    async def _parse_numeric_percentiles_robust(
        self, question: NumericQuestion, text: str, stage: str
    ) -> List[Percentile]:
        parser_llm = self.get_llm("parser", "llm")
        instructions = self._numeric_parsing_instructions(question)
        numeric_validation_samples = 1

        try:
            raw1: List[RawPercentile] = await structure_output(
                text,
                list[RawPercentile],
                model=parser_llm,
                additional_instructions=instructions,
                num_validation_samples=numeric_validation_samples,
            )
            p1 = self._normalize_raw_percentiles(raw1)
            std1 = self._require_standard_percentiles(p1)
            if std1:
                return self._enforce_monotone(std1)
        except Exception as e:
            logger.warning(f"[{stage}] numeric parse attempt 1 failed: {e}")

        block = self._extract_percentile_block(text)
        if block:
            try:
                raw2: List[RawPercentile] = await structure_output(
                    block,
                    list[RawPercentile],
                    model=parser_llm,
                    additional_instructions=instructions,
                    num_validation_samples=numeric_validation_samples,
                )
                p2 = self._normalize_raw_percentiles(raw2)
                std2 = self._require_standard_percentiles(p2)
                if std2:
                    return self._enforce_monotone(std2)
            except Exception as e:
                logger.warning(f"[{stage}] numeric parse attempt 2 failed: {e}")

        try:
            reform_prompt = clean_indents(
                f"""
Rewrite the answer into EXACTLY these 6 lines (no extra text):

Percentile 10: <number>
Percentile 20: <number>
Percentile 40: <number>
Percentile 60: <number>
Percentile 80: <number>
Percentile 90: <number>

Rules:
- Values must be in units: {question.unit_of_measure}
- Never use scientific notation.
- Values must be strictly increasing.

Text:
{text}
"""
            )
            reformatted = await parser_llm.invoke(reform_prompt)
            rb = self._extract_percentile_block(reformatted) or reformatted
            raw3: List[RawPercentile] = await structure_output(
                rb,
                list[RawPercentile],
                model=parser_llm,
                additional_instructions=instructions,
                num_validation_samples=numeric_validation_samples,
            )
            p3 = self._normalize_raw_percentiles(raw3)
            std3 = self._require_standard_percentiles(p3)
            if std3:
                return self._enforce_monotone(std3)
        except Exception as e:
            logger.warning(f"[{stage}] numeric parse attempt 3 failed: {e}")

        logger.warning(f"[{stage}] numeric parsing failed; using bounds fallback.")
        return self._bounds_fallback(question)

    # ------------------------------------------------------------------
    # Calibration helpers
    # ------------------------------------------------------------------

    def _get_temperature(self, question: MetaculusQuestion) -> float:
        if not getattr(question, "close_time", None):
            return 0.25
        days_to_close = (question.close_time - datetime.now(timezone.utc)).days
        qt = (question.question_text or "").lower()
        if days_to_close > 180 or "first" in qt or "never before" in qt:
            return 0.30
        return 0.10

    def _agreement_strength(self, probs: List[float]) -> float:
        if not probs:
            return 0.0
        spread = max(probs) - min(probs) if len(probs) > 1 else 0.0
        return float(np.clip(1.0 - (spread / 0.35), 0.0, 1.0))

    def _extremize_strength(
        self, research: str, probs: List[float], question: MetaculusQuestion
    ) -> float:
        """
        Extremize gate: ≥0.60 or ≤0.40 (logit method).
        Strength is modulated by research quality and model agreement.
        """
        if not self.flags.enable_extremize:
            return 1.0
        quality = self._research_quality_weight(research)
        agree = self._agreement_strength(probs)
        base = 1.0 + 0.9 * (quality - 0.5) * 2.0 * agree
        close_time = getattr(question, "close_time", None)
        if close_time:
            now = datetime.now(timezone.utc)
            days = (close_time - now).days
            if days < 14:
                base = 1.0 + (base - 1.0) * 0.3
            elif days < 60:
                base = 1.0 + (base - 1.0) * 0.6
        return float(np.clip(base, 0.9, 2.0))

    def _should_extremize(self, p: float) -> bool:
        """Gate: only extremize when base_p ≥ 0.60 or ≤ 0.40."""
        return p >= 0.60 or p <= 0.40

    # ------------------------------------------------------------------
    # Red team + consistency
    # ------------------------------------------------------------------

    async def _red_team_forecast(
        self, question: MetaculusQuestion, research: str, initial_pred: float
    ) -> float:
        self._ensure_some_research_or_raise(research)
        try:
            llm = self.get_llm("red_team", "llm")
            response = await llm.invoke(
                clean_indents(
                    f"""
You are a skeptical red teamer.

Question: {question.question_text}
Research:
{research}

Current forecast: {initial_pred:.2%}

Output ONLY JSON:
{{"revised_prediction_in_decimal": 0.XX}}
"""
                )
            )
            parsed = await structure_output(
                sanitize_llm_json(response),
                dict,
                model=self.get_llm("parser", "llm"),
                num_validation_samples=1,
            )
            if isinstance(parsed, dict) and "revised_prediction_in_decimal" in parsed:
                val = float(parsed["revised_prediction_in_decimal"])
                return float(np.clip(val, 0.0, 1.0))
        except Exception as e:
            logger.warning(f"Red teaming failed: {e}")
        return initial_pred

    async def _check_consistency(self, question: MetaculusQuestion, proposed_pred: float) -> bool:
        if len(self._recent_predictions) < 2:
            return True
        recent_summary = "\n".join(
            [
                f"Q: {getattr(q, 'question_text', '')} → Pred: {p:.2%}"
                for q, p in self._recent_predictions[-3:]
            ]
        )
        llm = self.get_llm("parser", "llm")
        prompt = f"""
Is this new forecast logically consistent with prior forecasts?

New: {question.question_text} → {proposed_pred:.2%}

Prior:
{recent_summary}

Answer YES or NO only.
""".strip()
        try:
            response = await llm.invoke(prompt)
            return "YES" in (response or "").upper()
        except Exception:
            return True

    # ------------------------------------------------------------------
    # Reasoning footers
    # ------------------------------------------------------------------

    def _methodology_header(self, research: str) -> str:
        return (
            f"[{self.bot_name}] methodology: research(sonar-small-online‖mistral-small-3.1-online→mistral-7b-auditor); "
            f"ensemble→critic→red-team; numeric regime routing + constrained parsing; "
            f"extremize(logit,gate≥0.60/≤0.40) when evidence quality+agreement supports it."
        )

    def _numeric_summary_line(self, pcts: List[Percentile]) -> str:
        med = self._median_from_40_60(pcts)
        p10, p90 = self._p10_p90(pcts)
        if p10 is not None and p90 is not None:
            return f"final summary: median≈{med:.6g}, 10–90≈[{p10:.6g},{p90:.6g}]"
        return f"final summary: median≈{med:.6g}"

    def _short_reasoning_binary(
        self,
        research: str,
        final_p: float,
        raw_p: float,
        red_p: float,
        extremized_p: float,
        spread: float,
        quality: float,
        applied: List[str],
    ) -> str:
        applied_txt = ", ".join(applied) if applied else "none"
        return (
            f"{self._methodology_header(research)} "
            f"Binary: ensemble→critic→red-team; controls({applied_txt}). "
            f"final={final_p:.3f} (critic={raw_p:.3f}, red={red_p:.3f}, "
            f"ext={extremized_p:.3f}, spread={spread:.3f}, q={quality:.2f})."
        )

    def _short_reasoning_mc(self, research: str, avg_prob: float) -> str:
        return (
            f"{self._methodology_header(research)} "
            f"MC: ensemble→critic; aligned+normalized option probs. final avg_prob={avg_prob:.3f}."
        )

    def _short_reasoning_numeric_generic(self, research: str, pcts: List[Percentile]) -> str:
        return (
            f"{self._methodology_header(research)} "
            f"Numeric(generic): ensemble→critic; parsed standard percentiles; monotone enforced. "
            f"{self._numeric_summary_line(pcts)}."
        )

    # ------------------------------------------------------------------
    # Numeric regime detection
    # ------------------------------------------------------------------

    def _extract_date_range_generic(self, text: str) -> Optional[Tuple[date, date]]:
        m = re.search(
            r"\(\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\s*-\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\s*\)",
            text or "",
            flags=re.IGNORECASE,
        )
        if not m:
            return None
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                start = datetime.strptime(m.group(1), fmt).date()
                end = datetime.strptime(m.group(2), fmt).date()
                if start > end:
                    start, end = end, start
                return start, end
            except Exception:
                continue
        return None

    def _has_partial_observations(self, research: str, question: NumericQuestion) -> bool:
        r = (research or "").lower()
        cues = [
            "sum to", "subtotal", "observed", "published", "known days",
            "so far", "remaining", "hinges on", "partial", "to date",
        ]
        return any(c in r for c in cues) and self._extract_date_range_generic(question.question_text or "") is not None

    def _regex_extract_known_subtotal(self, research: str) -> Optional[float]:
        pats = [
            r"sum to\s+([\d,]+(?:\.\d+)?)",
            r"subtotal[:\s]+([\d,]+(?:\.\d+)?)",
            r"known (?:subtotal|total)[:\s]+([\d,]+(?:\.\d+)?)",
            r"published (?:days|values) .*?sum(?:s)? to\s+([\d,]+(?:\.\d+)?)",
        ]
        for pat in pats:
            m = re.search(pat, research or "", flags=re.IGNORECASE)
            if m:
                try:
                    v = float(m.group(1).replace(",", ""))
                    if v > 0:
                        return v
                except Exception:
                    pass
        return None

    def _is_level_series_question(self, question: NumericQuestion) -> bool:
        qt = (question.question_text or "").lower()
        return any(k in qt for k in ["ending value", "end value", "closing value", "close value", "as of"])

    def _horizon_days_from_text(self, question: NumericQuestion) -> Optional[int]:
        dr = self._extract_date_range_generic(question.question_text or "")
        if not dr:
            return None
        start, end = dr
        return (end - start).days + 1

    def _detect_numeric_regime(self, question: NumericQuestion, research: str) -> NumericRegime:
        if not self.flags.enable_numeric_regimes:
            return NumericRegime.GENERIC
        qt = (question.question_text or "").lower()
        dr = self._extract_date_range_generic(question.question_text or "")
        if "according to" in qt and any(w in qt for w in ["was", "were", "did", "have"]):
            if dr:
                _, end = dr
                if end < datetime.now(timezone.utc).date():
                    return NumericRegime.LOOKUP
        if self._has_partial_observations(research, question):
            return NumericRegime.PARTIAL_REVEAL_SUM
        if dr:
            start, end = dr
            horizon = (end - start).days + 1
            if 2 <= horizon <= 31:
                return NumericRegime.STRUCTURED_TS
        if self._is_level_series_question(question):
            return NumericRegime.STRUCTURED_TS
        return NumericRegime.GENERIC

    # ------------------------------------------------------------------
    # Numeric regime forecasters
    # ------------------------------------------------------------------

    @staticmethod
    def _normal_percentiles_from_mean_sd(mean: float, sd: float) -> List[Percentile]:
        z = {0.1: -1.2816, 0.2: -0.8416, 0.4: -0.2533, 0.6: 0.2533, 0.8: 0.8416, 0.9: 1.2816}
        out: List[Percentile] = []
        for p in [0.1, 0.2, 0.4, 0.6, 0.8, 0.9]:
            out.append(Percentile(percentile=p, value=float(mean + z[p] * sd)))
        return OracleDeckV1._enforce_monotone(out)

    async def _bounded_multiplier(
        self, question: NumericQuestion, research: str, baseline: float, *, lo: float, hi: float
    ) -> float:
        critic = self.get_llm("critic", "llm")
        prompt = clean_indents(f"""
Return JSON only: {{"multiplier": 1.00}}

Question: {question.question_text}
Baseline: {baseline}
Research:
{research}

Rules:
- multiplier must be within [{lo:.6f}, {hi:.6f}]
- Output only JSON.
""")
        raw = await critic.invoke(prompt)
        model = safe_model(BoundedMultiplier, sanitize_llm_json(raw))  # type: ignore[arg-type]
        return float(np.clip(float(getattr(model, "multiplier")), lo, hi))

    async def _bounded_delta(
        self, question: NumericQuestion, research: str, baseline_level: float, *, lo: float, hi: float
    ) -> float:
        critic = self.get_llm("critic", "llm")
        prompt = clean_indents(f"""
Return JSON only: {{"delta": 0.00}}

Question: {question.question_text}
Baseline level: {baseline_level}
Research:
{research}

Rules:
- delta must be within [{lo:.6f}, {hi:.6f}]
- Output only JSON.
""")
        raw = await critic.invoke(prompt)
        model = safe_model(BoundedDelta, sanitize_llm_json(raw))  # type: ignore[arg-type]
        return float(np.clip(float(getattr(model, "delta")), lo, hi))

    async def _llm_extract_partial_reveal(
        self, question: NumericQuestion, research: str
    ) -> PartialRevealExtract:
        parser = self.get_llm("parser", "llm")
        prompt = clean_indents(f"""
Return JSON only:
{{"known_subtotal": null, "known_parts": null, "total_parts": null, "notes": null}}

Question:
{question.question_text}

Research:
{research}

Extract:
- known_subtotal if research states a subtotal/sum for observed parts
- known_parts and total_parts if inferable
""")
        raw = await parser.invoke(prompt)
        return safe_model(PartialRevealExtract, sanitize_llm_json(raw))  # type: ignore[return-value]

    async def _llm_extract_reference_class(
        self, question: NumericQuestion, research: str
    ) -> ReferenceClassExtract:
        parser = self.get_llm("parser", "llm")
        prompt = clean_indents(f"""
Return JSON only:
{{"reference_totals": [], "trend_multiplier": null, "notes": null}}

Question:
{question.question_text}

Research:
{research}

Extract comparable reference totals (last period, same period last year, etc.)
and an optional trend_multiplier.
""")
        raw = await parser.invoke(prompt)
        return safe_model(ReferenceClassExtract, sanitize_llm_json(raw))  # type: ignore[return-value]

    async def _llm_extract_level_series(
        self, question: NumericQuestion, research: str
    ) -> LevelSeriesExtract:
        parser = self.get_llm("parser", "llm")
        prompt = clean_indents(f"""
Return JSON only:
{{"current_value": null, "current_date": null, "recent_values": [], "notes": null}}

Question:
{question.question_text}

Research:
{research}

Extract the latest observed level and a few recent values if available.
""")
        raw = await parser.invoke(prompt)
        return safe_model(LevelSeriesExtract, sanitize_llm_json(raw))  # type: ignore[return-value]

    def _delta_bounds_for_horizon(self, horizon_days: Optional[int]) -> Tuple[float, float]:
        h = horizon_days if horizon_days is not None else 30
        if h <= 21:
            return (-0.60, 0.60)
        if h <= 60:
            return (-1.00, 1.00)
        return (-2.00, 2.00)

    def _mult_bounds_for_horizon(self, horizon_days: Optional[int]) -> Tuple[float, float]:
        h = horizon_days if horizon_days is not None else 30
        if h <= 21:
            return (0.97, 1.03)
        if h <= 60:
            return (0.95, 1.05)
        return (0.90, 1.10)

    async def _forecast_numeric_partial_reveal(
        self, question: NumericQuestion, research: str
    ) -> ReasonedPrediction[NumericDistribution]:
        known_rx = self._regex_extract_known_subtotal(research)
        extracted: Optional[PartialRevealExtract] = None
        try:
            extracted = await self._llm_extract_partial_reveal(question, research)
        except Exception as e:
            logger.warning(f"Partial-reveal extraction failed: {e}")

        known_subtotal = (
            float(extracted.known_subtotal)
            if (extracted and extracted.known_subtotal)
            else (float(known_rx) if known_rx else None)
        )
        known_parts = int(extracted.known_parts) if (extracted and extracted.known_parts is not None) else None
        total_parts = int(extracted.total_parts) if (extracted and extracted.total_parts is not None) else None

        if known_subtotal is None:
            return await self._run_forecast_on_numeric_generic(question, research)

        if known_parts and total_parts and total_parts > known_parts and known_parts > 0:
            per_part = known_subtotal / known_parts
            remainder_baseline = per_part * (total_parts - known_parts)
        else:
            remainder_baseline = 0.85 * known_subtotal

        lo_m, hi_m = self._mult_bounds_for_horizon(self._horizon_days_from_text(question))
        mult = await self._bounded_multiplier(question, research, remainder_baseline, lo=lo_m, hi=hi_m)
        remainder_mean = remainder_baseline * mult
        total_mean = known_subtotal + remainder_mean

        remainder_sd = max(0.08 * remainder_mean, 0.02 * total_mean)
        pcts = self._normal_percentiles_from_mean_sd(total_mean, remainder_sd)
        for p in pcts:
            if p.value < known_subtotal:
                p.value = known_subtotal
        pcts = self._enforce_monotone(pcts)

        dist = NumericDistribution.from_question(pcts, question)
        med = self._median_from_40_60(pcts)
        self._recent_predictions.append((question, float(med / (abs(med) + 1.0)) if med else 0.0))

        reasoning = (
            f"{self._methodology_header(research)} "
            f"Regime=partial_reveal_sum: locked known subtotal≈{known_subtotal:.6g}; "
            f"modeled remainder baseline≈{remainder_baseline:.6g} × bounded multiplier {mult:.4f}; "
            f"uncertainty on remainder only; enforced total≥known. {self._numeric_summary_line(pcts)}."
        )
        return ReasonedPrediction(prediction_value=dist, reasoning=reasoning)

    async def _forecast_numeric_level_series_endvalue(
        self, question: NumericQuestion, research: str
    ) -> ReasonedPrediction[NumericDistribution]:
        ex: Optional[LevelSeriesExtract] = None
        try:
            ex = await self._llm_extract_level_series(question, research)
        except Exception as e:
            logger.warning(f"Level-series extraction failed: {e}")

        level = float(ex.current_value) if (ex and ex.current_value is not None) else None
        if level is None or not np.isfinite(level) or level <= 0:
            return await self._forecast_numeric_structured_ts(question, research, force_non_level=True)

        horizon = self._horizon_days_from_text(question)
        lo_d, hi_d = self._delta_bounds_for_horizon(horizon)
        delta = await self._bounded_delta(question, research, level, lo=lo_d, hi=hi_d)
        mean = level + delta

        sd = None
        if ex and ex.recent_values and len(ex.recent_values) >= 5:
            vals = [float(v) for v in ex.recent_values if isinstance(v, (int, float)) and np.isfinite(v)]
            if len(vals) >= 5:
                changes = np.diff(vals)
                daily_sd = float(np.std(changes)) if len(changes) > 1 else 0.0
                h = float(horizon if horizon is not None else 10)
                sd = float(np.sqrt(max(2.0, h)) * max(daily_sd, 0.02))
        if sd is None:
            h = float(horizon if horizon is not None else 10)
            sd = float(np.clip(0.12 * np.sqrt(max(2.0, h)), 0.08, 0.90))

        pcts = self._normal_percentiles_from_mean_sd(mean, sd)

        lo = float(question.lower_bound)
        hi = float(question.upper_bound)
        if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
            for p in pcts:
                p.value = float(np.clip(p.value, lo, hi))
            pcts = self._enforce_monotone(pcts)

        dist = NumericDistribution.from_question(pcts, question)
        med = self._median_from_40_60(pcts)
        self._recent_predictions.append((question, float(med / (abs(med) + 1.0)) if med else 0.0))

        reasoning = (
            f"{self._methodology_header(research)} "
            f"Regime=level_series_endvalue: baseline(latest)≈{level:.6g}; "
            f"bounded delta={delta:.4g} within [{lo_d:.3g},{hi_d:.3g}] horizon≈{horizon or 'n/a'}d; "
            f"sd from recent volatility if available else conservative default. {self._numeric_summary_line(pcts)}."
        )
        return ReasonedPrediction(prediction_value=dist, reasoning=reasoning)

    async def _forecast_numeric_structured_ts(
        self, question: NumericQuestion, research: str, *, force_non_level: bool = False
    ) -> ReasonedPrediction[NumericDistribution]:
        if (not force_non_level) and self._is_level_series_question(question):
            return await self._forecast_numeric_level_series_endvalue(question, research)

        lo = float(question.lower_bound)
        hi = float(question.upper_bound)
        baseline = 0.5 * (lo + hi) if np.isfinite(lo) and np.isfinite(hi) and hi > lo else 1.0

        try:
            ref = await self._llm_extract_reference_class(question, research)
            refs = [
                float(x)
                for x in (ref.reference_totals or [])
                if isinstance(x, (int, float)) and x > 0 and np.isfinite(x)
            ]
            if refs:
                baseline = float(np.median(refs))
                if ref.trend_multiplier and np.isfinite(float(ref.trend_multiplier)):
                    tm = float(ref.trend_multiplier)
                    if 0.8 <= tm <= 1.2:
                        baseline *= tm
        except Exception as e:
            logger.warning(f"Structured TS extraction failed: {e}")

        horizon = self._horizon_days_from_text(question)
        lo_m, hi_m = self._mult_bounds_for_horizon(horizon)
        mult = await self._bounded_multiplier(question, research, baseline, lo=lo_m, hi=hi_m)
        mean = baseline * mult

        width = (hi - lo) if np.isfinite(hi - lo) and (hi - lo) > 0 else None
        sd = max(0.06 * abs(mean), 0.02 * width) if width is not None else 0.06 * abs(mean)
        sd = float(np.clip(sd, 1e-9, max(1e-9, 0.25 * abs(mean) + 1e-9)))

        pcts = self._normal_percentiles_from_mean_sd(mean, sd)

        if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
            for p in pcts:
                p.value = float(np.clip(p.value, lo, hi))
            pcts = self._enforce_monotone(pcts)

        dist = NumericDistribution.from_question(pcts, question)
        med = self._median_from_40_60(pcts)
        self._recent_predictions.append((question, float(med / (abs(med) + 1.0)) if med else 0.0))

        reasoning = (
            f"{self._methodology_header(research)} "
            f"Regime=structured_ts: baseline≈{baseline:.6g}; bounded multiplier x{mult:.4f} "
            f"within [{lo_m:.3f},{hi_m:.3f}] horizon≈{horizon or 'n/a'}d; "
            f"short-horizon sd heuristic; monotone enforced. {self._numeric_summary_line(pcts)}."
        )
        return ReasonedPrediction(prediction_value=dist, reasoning=reasoning)

    # ------------------------------------------------------------------
    # Per-model forecast helper
    # ------------------------------------------------------------------

    async def _get_model_forecast(
        self, model_name: str, question: MetaculusQuestion, research: str
    ) -> Any:
        self._ensure_some_research_or_raise(research)
        temp = self._get_temperature(question)
        llm = GeneralLlm(model=model_name, temperature=temp)

        if isinstance(question, BinaryQuestion):
            raw = await llm.invoke(
                clean_indents(
                    f"""
Question: {question.question_text}

Research:
{research}

OUTPUT ONLY VALID JSON:
{{"prediction_in_decimal": 0.35}}
"""
                )
            )
            return await structure_output(
                sanitize_llm_json(raw),
                BinaryPrediction,
                model=self.get_llm("parser", "llm"),
                num_validation_samples=self._structure_output_validation_samples,
            )

        if isinstance(question, MultipleChoiceQuestion):
            schema_example = json.dumps(
                {"predicted_options": [{"option_name": opt, "probability": 0.5} for opt in question.options[:2]]}
            )
            raw = await llm.invoke(
                clean_indents(
                    f"""
Question: {question.question_text}
Options: {question.options}

Research:
{research}

OUTPUT ONLY VALID JSON:
{schema_example}
"""
                )
            )
            return await structure_output(
                sanitize_llm_json(raw),
                PredictedOptionList,
                model=self.get_llm("parser", "llm"),
                num_validation_samples=self._structure_output_validation_samples,
            )

        if isinstance(question, NumericQuestion):
            upper_msg, lower_msg = self._create_upper_and_lower_bound_messages(question)
            units = question.unit_of_measure if question.unit_of_measure else "Not stated"
            reasoning = await llm.invoke(
                clean_indents(
                    f"""
Question:
{question.question_text}

Units: {units}

Research:
{research}

Today is {datetime.now().strftime("%Y-%m-%d")}.

{lower_msg}
{upper_msg}

The LAST thing you write is EXACTLY:
"
Percentile 10: XX
Percentile 20: XX
Percentile 40: XX
Percentile 60: XX
Percentile 80: XX
Percentile 90: XX
"
"""
                )
            )
            return await self._parse_numeric_percentiles_robust(
                question, reasoning, stage=f"model_forecast:{model_name}"
            )

        raise TypeError(f"Unsupported question type: {type(question)}")

    # ------------------------------------------------------------------
    # Main forecast methods
    # ------------------------------------------------------------------

    async def _run_forecast_on_binary(
        self, question: BinaryQuestion, research: str
    ) -> ReasonedPrediction[float]:
        self._ensure_some_research_or_raise(research)

        forecasters = [
            "openrouter/meta-llama/llama-3.3-70b-instruct:free",
            "openrouter/mistralai/mistral-7b-instruct:free",
        ]
        results = await asyncio.gather(
            *[self._get_model_forecast(m, question, research) for m in forecasters]
        )
        model_probs = [float(r.prediction_in_decimal) for r in results]
        forecast_map: Dict[str, float] = {
            f"model_{i}": float(r.prediction_in_decimal) for i, r in enumerate(results)
        }
        spread = (max(model_probs) - min(model_probs)) if len(model_probs) > 1 else 0.0

        critic_llm = self.get_llm("critic", "llm")
        critique = await critic_llm.invoke(
            clean_indents(
                f"""
Question: {question.question_text}

Research:
{research}

Ensemble model forecasts:
{json.dumps(forecast_map)}

OUTPUT ONLY JSON:
{{"prediction_in_decimal": 0.75}}
"""
            )
        )
        critic_out = await structure_output(
            sanitize_llm_json(critique),
            BinaryPrediction,
            model=self.get_llm("parser", "llm"),
            num_validation_samples=self._structure_output_validation_samples,
        )
        raw_p = float(critic_out.prediction_in_decimal)

        red_teamed_p = await self._red_team_forecast(question, research, raw_p)
        averaged_p = 0.5 * (raw_p + red_teamed_p)

        applied: List[str] = []
        if spread >= 0.35:
            averaged_p = 0.6 * averaged_p + 0.4 * 0.5
            applied.append("high-spread-shrink")
        elif spread >= 0.20:
            averaged_p = 0.8 * averaged_p + 0.2 * 0.5
            applied.append("med-spread-shrink")

        if not await self._check_consistency(question, averaged_p):
            averaged_p = 0.5 * averaged_p + 0.5 * 0.5
            applied.append("consistency-shrink")

        community = getattr(question, "community_prediction", None)
        quality = self._research_quality_weight(research)
        blended_p = (
            (quality * averaged_p + (1 - quality) * float(community))
            if (community is not None)
            else averaged_p
        )
        if community is not None:
            applied.append("community-blend")

        # Extremize gate: ≥0.60 or ≤0.40 only
        ext_strength = self._extremize_strength(research, model_probs + [raw_p, red_teamed_p], question)
        if self.flags.enable_extremize and self._should_extremize(blended_p):
            p_ext = ForecastingPrinciples.extremize_logit(blended_p, ext_strength)
            if abs(ext_strength - 1.0) > 0.05:
                applied.append(f"extremize(x{ext_strength:.2f})")
        else:
            p_ext = blended_p

        p_time = ForecastingPrinciples.apply_time_decay(p_ext, getattr(question, "close_time", None))
        if p_time != p_ext:
            applied.append("time-decay")

        try:
            p_cal = self.apply_bayesian_calibration(p_time * 100) / 100.0
            if p_cal != p_time:
                applied.append("bayes-calibration")
        except Exception:
            p_cal = p_time

        final_p = float(np.clip(p_cal, 0.01, 0.99))
        self._recent_predictions.append((question, final_p))

        reasoning = self._short_reasoning_binary(
            research=research,
            final_p=final_p,
            raw_p=raw_p,
            red_p=red_teamed_p,
            extremized_p=p_ext,
            spread=spread,
            quality=quality,
            applied=applied,
        )
        return ReasonedPrediction(prediction_value=final_p, reasoning=reasoning)

    async def _run_forecast_on_multiple_choice(
        self, question: MultipleChoiceQuestion, research: str
    ) -> ReasonedPrediction[PredictedOptionList]:
        self._ensure_some_research_or_raise(research)

        forecasters = [
            "openrouter/meta-llama/llama-3.3-70b-instruct:free",
            "openrouter/mistralai/mistral-7b-instruct:free",
        ]
        results = await asyncio.gather(
            *[self._get_model_forecast(m, question, research) for m in forecasters]
        )
        forecast_map = {f"model_{i}": r.model_dump() for i, r in enumerate(results)}

        critic_llm = self.get_llm("critic", "llm")
        schema_example = json.dumps(
            {"predicted_options": [{"option_name": opt, "probability": 0.5} for opt in question.options[:2]]}
        )
        critique = await critic_llm.invoke(
            clean_indents(
                f"""
Question: {question.question_text}
Options: {question.options}

Research:
{research}

Ensemble model forecasts:
{json.dumps(forecast_map)}

OUTPUT ONLY VALID JSON:
{schema_example}
"""
            )
        )
        final_list: PredictedOptionList = await structure_output(
            sanitize_llm_json(critique),
            PredictedOptionList,
            model=self.get_llm("parser", "llm"),
            num_validation_samples=self._structure_output_validation_samples,
        )

        option_names = question.options
        current = {o.option_name: float(o.probability) for o in final_list.predicted_options}
        aligned = [{"option_name": name, "probability": float(current.get(name, 0.0))} for name in option_names]
        total = float(sum(o["probability"] for o in aligned))
        if total <= 0:
            uniform = 1.0 / len(aligned)
            for o in aligned:
                o["probability"] = uniform
        else:
            for o in aligned:
                o["probability"] /= total

        final_val = safe_model(PredictedOptionList, {"predicted_options": aligned})  # type: ignore[assignment]
        avg_prob = float(np.mean([o["probability"] for o in aligned])) if aligned else 0.0
        self._recent_predictions.append((question, avg_prob))

        return ReasonedPrediction(
            prediction_value=final_val,
            reasoning=self._short_reasoning_mc(research, avg_prob),
        )

    async def _run_forecast_on_numeric_generic(
        self, question: NumericQuestion, research: str
    ) -> ReasonedPrediction[NumericDistribution]:
        self._ensure_some_research_or_raise(research)

        forecasters = [
            "openrouter/meta-llama/llama-3.3-70b-instruct:free",
            "openrouter/mistralai/mistral-7b-instruct:free",
        ]
        results: List[List[Percentile]] = await asyncio.gather(
            *[self._get_model_forecast(m, question, research) for m in forecasters]
        )
        forecast_map = {
            f"model_{i}": [{"percentile": float(p.percentile), "value": float(p.value)} for p in r]
            for i, r in enumerate(results)
        }
        upper_msg, lower_msg = self._create_upper_and_lower_bound_messages(question)
        units = question.unit_of_measure if question.unit_of_measure else "Not stated"
        critic_llm = self.get_llm("critic", "llm")

        critique = await critic_llm.invoke(
            clean_indents(
                f"""
Question:
{question.question_text}

Units: {units}

Research:
{research}

Ensemble forecasts:
{json.dumps(forecast_map)}

Today is {datetime.now().strftime("%Y-%m-%d")}.

{lower_msg}
{upper_msg}

The LAST thing you write is EXACTLY:
"
Percentile 10: XX
Percentile 20: XX
Percentile 40: XX
Percentile 60: XX
Percentile 80: XX
Percentile 90: XX
"
"""
            )
        )

        final_pcts = await self._parse_numeric_percentiles_robust(question, critique, stage="critic_numeric")
        final_pcts = self._enforce_monotone(final_pcts)

        dist = NumericDistribution.from_question(final_pcts, question)
        med = self._median_from_40_60(final_pcts)
        self._recent_predictions.append((question, float(med / (abs(med) + 1.0)) if med else 0.0))

        return ReasonedPrediction(
            prediction_value=dist,
            reasoning=self._short_reasoning_numeric_generic(research, final_pcts),
        )

    async def _run_forecast_on_numeric(
        self, question: NumericQuestion, research: str
    ) -> ReasonedPrediction[NumericDistribution]:
        self._ensure_some_research_or_raise(research)
        if not self.flags.enable_numeric_regimes:
            return await self._run_forecast_on_numeric_generic(question, research)

        regime = self._detect_numeric_regime(question, research)

        if regime == NumericRegime.PARTIAL_REVEAL_SUM:
            try:
                return await self._forecast_numeric_partial_reveal(question, research)
            except Exception as e:
                logger.warning(f"Partial-reveal regime failed, fallback to generic: {e}")
                return await self._run_forecast_on_numeric_generic(question, research)

        if regime == NumericRegime.STRUCTURED_TS:
            try:
                return await self._forecast_numeric_structured_ts(question, research)
            except Exception as e:
                logger.warning(f"Structured TS regime failed, fallback to generic: {e}")
                return await self._run_forecast_on_numeric_generic(question, research)

        return await self._run_forecast_on_numeric_generic(question, research)

    async def _run_forecast_on_numeric_wrapper(
        self, question: NumericQuestion, research: str
    ) -> ReasonedPrediction[NumericDistribution]:
        return await self._run_forecast_on_numeric(question, research)


# ---------------------------------------------------------------------------
# Entry point — Spring Tournament only
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="OracleDeck v1 — Spring Tournament bot")
    parser.add_argument("--bot-name",           type=str,  default="oracledeckv1")
    parser.add_argument("--no-extremize",        action="store_true")
    parser.add_argument("--no-decomposition",    action="store_true")
    parser.add_argument("--no-numeric-regimes",  action="store_true")
    parser.add_argument(
        "--tournament-id",
        type=str,
        default=SPRING_TOURNAMENT_ID,
        help="Override the Spring Tournament ID/slug if Metaculus changes it.",
    )
    args = parser.parse_args()

    flags = BotFeatureFlags(
        enable_extremize=not args.no_extremize,
        enable_decomposition=not args.no_decomposition,
        enable_numeric_regimes=not args.no_numeric_regimes,
    )


    bot = OracleDeckV1(
        research_reports_per_question=1,
        predictions_per_research_report=1,
        use_research_summary_to_forecast=False,
        publish_reports_to_metaculus=True,
        skip_previously_forecasted_questions=True,
        extra_metadata_in_explanation=True,
        bot_name=args.bot_name,
        flags=flags,
    )

    async def run():
        client = MetaculusClient()
        logger.info(f"[oracledeckv1] Forecasting Spring Tournament: {args.tournament_id}")
        logger.info(f"[oracledeckv1] Forecasting Mini Bench: {client.CURRENT_MINIBENCH_ID}")
        spring_reports, minibench_reports = await asyncio.gather(
            bot.forecast_on_tournament(args.tournament_id, return_exceptions=True),
            bot.forecast_on_tournament(client.CURRENT_MINIBENCH_ID, return_exceptions=True),
        )
        bot.log_report_summary(spring_reports + minibench_reports)

    asyncio.run(run())

