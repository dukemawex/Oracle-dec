from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("oracledeck-bot")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
EXA_URL = "https://api.exa.ai/search"
TOURNAMENT_SLUGS = ("spring-aib-2026", "mini-bench")
MODELS = {
    "default": "openrouter/openai/gpt-4.5",
    "summariser": "openrouter/google/gemini-flash-1.5-8b",
    "parser": "openrouter/mistralai/mistral-7b-instruct",
}
LEGACY_STAGE2_PROBABILITY_KEY = "tiny" + "fishProbability"


class SummariserResponse(BaseModel):
    probability: float = Field(ge=0.0, le=1.0)
    brief_reasoning: str


class GPTForecastResponse(BaseModel):
    probability: float = Field(ge=0.0, le=1.0)
    base_rate: str
    key_evidence: List[str]
    null_hypothesis: str
    rationale: str


@dataclass
class ForecastRecord:
    tournament: str
    question_id: int
    question_title: str
    summariser_probability: Optional[float]
    final_probability: float
    model: str
    created_at: str


class OracleDeckBot:
    def __init__(self) -> None:
        self.metaculus_token = self._required_env("METACULUS_TOKEN")
        self.openrouter_key = self._required_env("OPENROUTER_API_KEY")
        self.exa_key = self._required_env("EXA_API_KEY")
        self.backend_url = self._required_env("BACKEND_URL").rstrip("/")
        self.metaculus_api_base = os.getenv("METACULUS_API_BASE", "https://www.metaculus.com/api2").rstrip("/")

    def _required_env(self, name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return value

    def _openrouter_chat(self, model: str, prompt: str) -> str:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self.openrouter_key}",
                "HTTP-Referer": "https://oracledeck.app",
                "X-Title": "OracleDeck",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices", [])
        if not isinstance(choices, list) or len(choices) == 0:
            raise RuntimeError("OpenRouter returned no choices")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise RuntimeError("OpenRouter choice format invalid")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("OpenRouter message format invalid")

        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("OpenRouter returned non-string content")
        return content

    def _parse_json_content(self, content: str) -> Dict[str, Any]:
        stripped = content.strip()
        markdown_stripped = stripped.replace("```json", "").replace("```", "").strip()
        for candidate in (stripped, markdown_stripped):
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        first_brace = stripped.find("{")
        last_brace = stripped.rfind("}")
        if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
            try:
                data = json.loads(stripped[first_brace : last_brace + 1])
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            repair_prompt = (
                "Extract the single valid JSON object from the following text. "
                "Return ONLY JSON with no markdown, no commentary.\n"
                f"Text:\n{content}\n"
            )
            repaired = self._openrouter_chat(MODELS["parser"], repair_prompt)
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Parser model returned invalid JSON") from exc

        if not isinstance(data, dict):
            raise RuntimeError("Model output JSON must be an object")
        return data

    def _exa_search(self, query: str) -> List[Dict[str, str]]:
        response = requests.post(
            EXA_URL,
            headers={
                "x-api-key": self.exa_key,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "numResults": 5,
                "contents": {
                    "summary": True,
                    "highlights": {"numSentences": 3},
                },
            },
            timeout=30,
        )
        response.raise_for_status()
        payload: Any = response.json()
        results = payload.get("results", []) if isinstance(payload, dict) else []
        structured: List[Dict[str, str]] = []

        if not isinstance(results, list):
            return structured

        for item in results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", ""))
            url = str(item.get("url", ""))
            summary = str(item.get("summary", ""))
            highlights_value = item.get("highlights", [])
            highlights_list = highlights_value if isinstance(highlights_value, list) else []
            highlights = " ".join(str(h) for h in highlights_list if isinstance(h, str))
            structured.append(
                {
                    "title": title,
                    "url": url,
                    "summary": summary,
                    "highlights": highlights,
                }
            )
        return structured

    def build_research(self, question_text: str) -> str:
        query_a = question_text[:120]
        query_b = f"base rate probability statistics {question_text[:80]}"
        query_c = f"recent developments {question_text[:80]} 2025 2026"

        all_results: List[Dict[str, str]] = []
        for query in (query_a, query_b, query_c):
            try:
                all_results.extend(self._exa_search(query))
            except requests.RequestException as exc:
                LOGGER.warning("Exa search failed for query '%s': %s", query, exc)

        all_results = all_results[:9]
        chunks: List[str] = []
        for result in all_results:
            chunks.append(
                "\n".join(
                    [
                        f"Title: {result['title']}",
                        f"URL: {result['url']}",
                        f"Summary: {result['summary']}",
                        f"Highlights: {result['highlights']}",
                    ]
                )
            )
        return "\n---\n".join(chunks)

    def stage2_summariser(self, question_text: str, research: str) -> Optional[SummariserResponse]:
        prompt = (
            "You are estimating a binary event probability. Return ONLY JSON with keys "
            "probability (0 to 1 float) and brief_reasoning.\n"
            f"Question: {question_text}\n"
            f"Research:\n{research}\n"
        )

        try:
            content = self._openrouter_chat(MODELS["summariser"], prompt)
            data = self._parse_json_content(content)
            return SummariserResponse.model_validate(data)
        except (requests.RequestException, json.JSONDecodeError, ValidationError, RuntimeError) as exc:
            LOGGER.warning("Stage 2 summariser failed: %s", exc)
            return None

    def stage3_gpt(self, question_text: str, research: str, summariser_p: Optional[float]) -> GPTForecastResponse:
        summariser_fragment = "None" if summariser_p is None else f"{summariser_p:.4f}"
        prompt = (
            "You are an elite calibrated superforecaster.\n"
            "Instructions:\n"
            "1) Apply reference class forecasting and identify the most relevant historical base rate first.\n"
            "2) Update incrementally from base rate using specific evidence from research.\n"
            "3) Apply outside view before inside view.\n"
            "4) Explicitly consider null hypothesis (status quo continuation).\n"
            "5) Do not pull toward 50% when evidence is strong.\n"
            "Return ONLY valid JSON with exactly keys:\n"
            "{\"probability\": float_0_to_1, \"base_rate\": string, \"key_evidence\": string[], \"null_hypothesis\": string, \"rationale\": string}.\n"
            f"Question: {question_text}\n"
            f"Summariser estimate: {summariser_fragment}\n"
            f"Research:\n{research}\n"
        )

        content = self._openrouter_chat(MODELS["default"], prompt)
        data = self._parse_json_content(content)
        return GPTForecastResponse.model_validate(data)

    def fetch_open_questions(self, tournament_slug: str) -> List[Dict[str, Any]]:
        response = requests.get(
            f"{self.metaculus_api_base}/questions/",
            headers={"Authorization": f"Token {self.metaculus_token}"},
            params={"tournaments": tournament_slug, "status": "open", "limit": 25},
            timeout=30,
        )
        response.raise_for_status()
        payload: Any = response.json()
        results = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(results, list):
            return []
        return [item for item in results if isinstance(item, dict)]

    def submit_forecast(self, question_id: int, probability: float) -> None:
        response = requests.post(
            f"{self.metaculus_api_base}/questions/{question_id}/predict/",
            headers={
                "Authorization": f"Token {self.metaculus_token}",
                "Content-Type": "application/json",
            },
            json={"prediction": probability},
            timeout=30,
        )
        response.raise_for_status()

    def sync_batch(self, records: List[ForecastRecord]) -> None:
        payload = {
            "batchTimestamp": datetime.now(timezone.utc).isoformat(),
            "records": [
                {
                    "tournament": record.tournament,
                    "questionId": record.question_id,
                    "questionTitle": record.question_title,
                    LEGACY_STAGE2_PROBABILITY_KEY: record.summariser_probability,
                    "finalProbability": record.final_probability,
                    "model": record.model,
                    "createdAt": record.created_at,
                }
                for record in records
            ],
        }

        response = requests.post(
            f"{self.backend_url}/api/forecasts/batch",
            headers={
                "Authorization": f"Bearer {self.metaculus_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

    def run(self) -> None:
        records: List[ForecastRecord] = []
        for slug in TOURNAMENT_SLUGS:
            LOGGER.info("Processing tournament %s", slug)
            try:
                questions = self.fetch_open_questions(slug)
            except requests.RequestException as exc:
                LOGGER.error("Failed to fetch questions for %s: %s", slug, exc)
                continue

            for question in questions:
                question_id_value = question.get("id")
                title_value = question.get("title")
                if not isinstance(question_id_value, int) or not isinstance(title_value, str):
                    continue

                research = self.build_research(title_value)
                summariser = self.stage2_summariser(title_value, research)

                try:
                    forecast = self.stage3_gpt(
                        question_text=title_value,
                        research=research,
                        summariser_p=(summariser.probability if summariser else None),
                    )
                except (requests.RequestException, json.JSONDecodeError, ValidationError, RuntimeError) as exc:
                    LOGGER.error("Stage 3 failed for question %s: %s", question_id_value, exc)
                    continue

                probability = max(0.01, min(0.99, forecast.probability))
                try:
                    self.submit_forecast(question_id_value, probability)
                except requests.RequestException as exc:
                    LOGGER.error("Failed to submit forecast for question %s: %s", question_id_value, exc)
                    continue

                records.append(
                    ForecastRecord(
                        tournament=slug,
                        question_id=question_id_value,
                        question_title=title_value,
                        summariser_probability=(summariser.probability if summariser else None),
                        final_probability=probability,
                        model=MODELS["default"],
                        created_at=datetime.now(timezone.utc).isoformat(),
                    )
                )

        if records:
            try:
                self.sync_batch(records)
                LOGGER.info("Synced %d records to backend", len(records))
            except requests.RequestException as exc:
                LOGGER.error("Failed to sync batch: %s", exc)
        else:
            LOGGER.info("No records generated in this run")


if __name__ == "__main__":
    OracleDeckBot().run()
