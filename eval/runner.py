"""Eval runner — calls agent LLM and LLM-as-judge for each golden dataset case."""
from __future__ import annotations

import csv
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from eval.prompts import (
    AGENT_SYSTEM_PROMPT_MOCK_KNOWLEDGE,
    AGENT_SYSTEM_PROMPT_MOCK_STATE,
    JUDGE_SYSTEM_PROMPT,
    JUDGE_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "openai/gpt-4o-mini")

_FORMAT_REMINDER = """
You MUST respond with a JSON object:
{"actions": [{"type": "<action_type>", "payload": {...}}, ..., {"type": "send_message", "payload": {"content": "..."}}]}
The last action must always be send_message."""


# ── Data loading ──────────────────────────────────────────────────────────────

def load_golden_dataset(path: str = "data/golden_dataset.csv") -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_agent_system_prompt(config: dict) -> str:
    template = config["system_prompt"]["template"]
    actions_json = json.dumps(config["actions"]["available"], indent=2, ensure_ascii=False)

    prompt = template
    prompt = prompt.replace(
        "{current_datetime}",
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    prompt = prompt.replace("{personality.prompt}", config["personality"]["prompt"])
    prompt = prompt.replace("{knowledge_docs}", AGENT_SYSTEM_PROMPT_MOCK_KNOWLEDGE)
    prompt = prompt.replace("{actions}", actions_json)
    prompt = prompt.replace("{state_context}", AGENT_SYSTEM_PROMPT_MOCK_STATE)
    return prompt


# ── LLM callers ───────────────────────────────────────────────────────────────

async def _call_ollama(
    ollama_url: str,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.1,
    json_mode: bool = True,
) -> str:
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": temperature},
        "keep_alive": -1,
    }
    if json_mode:
        body["format"] = "json"

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)
    ) as client:
        resp = await client.post(f"{ollama_url}/api/chat", json=body)
        resp.raise_for_status()
    return resp.json()["message"]["content"]


async def _call_openrouter(
    api_key: str,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.0,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/antartia",
        "X-Title": "Antartia Eval",
    }
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(OPENROUTER_URL, headers=headers, json=body)
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ── Agent + judge calls ───────────────────────────────────────────────────────

async def call_agent(
    user_input: str,
    system_prompt: str,
    ollama_url: str,
    model: str,
) -> str:
    """Call the agent (Ollama) and return its raw response."""
    user_with_hint = user_input + "\n\n" + _FORMAT_REMINDER
    return await _call_ollama(
        ollama_url=ollama_url,
        model=model,
        system=system_prompt,
        user=user_with_hint,
        temperature=0.1,
        json_mode=True,
    )


async def call_judge(
    row: dict,
    agent_response: str,
    api_key: str,
    model: str = DEFAULT_JUDGE_MODEL,
) -> dict:
    """Call the judge (OpenRouter) and return parsed scores."""
    user_prompt = JUDGE_USER_TEMPLATE.format(
        category=row["category"],
        trigger=row["trigger"],
        input=row["input"],
        expected_actions_sequence=row["expected_actions_sequence"],
        expected_output_contains=row["expected_output_contains"],
        must_not=row["must_not"],
        persona_notes=row["persona_notes"],
        agent_response=agent_response[:4000],
    )
    raw = await _call_openrouter(
        api_key=api_key,
        model=model,
        system=JUDGE_SYSTEM_PROMPT,
        user=user_prompt,
        temperature=0.0,
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        logger.warning("Judge returned unparseable response: %s", raw[:300])
        return {
            "tool_sequence": 0,
            "output_quality": 0,
            "persona": 0,
            "must_not_violated": False,
            "verdict": "FAIL",
            "notes": "judge parse error",
        }


# ── Case runner ───────────────────────────────────────────────────────────────

async def run_case(
    row: dict,
    system_prompt: str,
    ollama_url: str,
    agent_model: str,
    openrouter_api_key: str,
    judge_model: str = DEFAULT_JUDGE_MODEL,
) -> dict[str, Any]:
    """Run one eval case: agent call → judge call → merged result."""
    case_id = row["id"]

    try:
        agent_response = await call_agent(
            user_input=row["input"],
            system_prompt=system_prompt,
            ollama_url=ollama_url,
            model=agent_model,
        )
    except Exception as exc:
        logger.error("Agent call failed for case %s: %s", case_id, exc)
        agent_response = f"[agent call failed: {exc}]"

    try:
        scores = await call_judge(
            row=row,
            agent_response=agent_response,
            api_key=openrouter_api_key,
            model=judge_model,
        )
    except Exception as exc:
        logger.error("Judge call failed for case %s: %s", case_id, exc)
        scores = {
            "tool_sequence": 0,
            "output_quality": 0,
            "persona": 0,
            "must_not_violated": False,
            "verdict": "FAIL",
            "notes": f"judge call failed: {exc}",
        }

    return {
        "id": case_id,
        "category": row["category"],
        "input": row["input"],
        "agent_response": agent_response,
        **scores,
    }
