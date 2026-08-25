import json
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..utils.logging_utils import get_logger

LOG = get_logger()

MODEL: str = "gemini-2.5-flash"
API: str = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENROUTER_API: str = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_DEFAULT_MODEL: str = "openrouter/auto"

BATCH_CATEGORIZE: int = 200
BATCH_PLAN: int = 100


def _ask(api_key: str, prompt: str, timeout: int = 60, max_tokens: int = 2000,
         provider: str = "gemini", model: Optional[str] = None,
         json_mode: bool = False) -> str:
    if not api_key:
        raise RuntimeError("No API key configured (free Gemini key from "
                           "Google AI Studio, or an OpenRouter key - "
                           "no credit card needed for Gemini).")
    if provider == "openrouter":
        payload: dict[str, Any] = {
            "model": model or OPENROUTER_DEFAULT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers: dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(OPENROUTER_API, headers=headers,
                                 json=payload, timeout=timeout)
            resp.raise_for_status()
        except requests.HTTPError:
            if json_mode and resp.status_code in (400, 422):
                payload.pop("response_format", None)
                resp = requests.post(OPENROUTER_API, headers=headers,
                                     json=payload, timeout=timeout)
                resp.raise_for_status()
            else:
                raise
        data = resp.json()
        content: Optional[str] = data["choices"][0]["message"].get("content")
        if not content:
            payload["max_tokens"] = max_tokens * 2
            resp = requests.post(OPENROUTER_API, headers=headers,
                                 json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"].get("content")
        if not content:
            raise RuntimeError("model returned an empty response "
                               "(reasoning-only or rate-limited)")
        return content.strip()
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": max_tokens,
        },
    }
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"
    headers = {"x-goog-api-key": api_key}
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        try:
            resp = requests.post(
                API.format(model=model or MODEL),
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            if resp.status_code == 429:
                wait = min(2 ** attempt * 2, 30)
                LOG.warning(f"Gemini rate limited, retrying in {wait}s (attempt {attempt + 1}/3)")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except requests.HTTPError as exc:
            last_exc = exc
            if resp.status_code >= 500:
                wait = min(2 ** attempt, 10)
                LOG.warning(f"Gemini server error {resp.status_code}, retrying in {wait}s")
                time.sleep(wait)
                continue
            raise
        except requests.ConnectionError:
            wait = min(2 ** attempt, 10)
            LOG.warning(f"Gemini connection error, retrying in {wait}s")
            time.sleep(wait)
            continue
    raise RuntimeError(f"Gemini API failed after retries: {last_exc}")


def _parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def summarize(api_key: str, data: dict[str, Any], timeout: int = 60,
              provider: str = "gemini",
              model: Optional[str] = None) -> str:
    prompt = (
        "You are a data-hygiene assistant for someone whose Google Drive is "
        "full. Write a concise, friendly executive summary (max 250 words) of "
        "this backup and analysis JSON. Highlight: total size, the biggest "
        "space hogs, duplicate waste, junk worth deleting, any verification "
        "issues, and 3 concrete recommendations. Use plain text with short "
        "sections, no markdown tables.\n\n"
        f"DATA:\n{json.dumps(data, default=str)[:30000]}"
    )
    try:
        text = _ask(api_key, prompt, timeout=timeout, max_tokens=800,
                    provider=provider, model=model)
    except Exception as exc:
        LOG.error(f"AI summarize failed: {exc}")
        raise RuntimeError(f"AI request failed: {exc}") from exc
    return text


def ai_categorize(api_key: str, names: List[str], timeout: int = 60,
                  provider: str = "gemini",
                  model: Optional[str] = None) -> Dict[str, str]:
    if not names:
        return {}
    names = list(dict.fromkeys(str(n) for n in names))
    result: Dict[str, str] = {}
    cats = ", ".join(sorted(_CATEGORIES_JSON))
    for i in range(0, len(names), BATCH_CATEGORIZE):
        batch = names[i:i + BATCH_CATEGORIZE]
        prompt = (
            "You are classifying files in a Google Drive. Based ONLY on the "
            "filename (and extension), assign each file to exactly one of "
            f"these categories: {cats}. If you are not sure, use \"Other\". "
            "Return STRICT JSON only, an object mapping each exact filename "
            "to its category:\n{\"filename.ext\": \"Category\"}\n\n"
            f"FILENAMES:\n{json.dumps(batch)}"
        )
        try:
            parsed = _parse_json(_ask(api_key, prompt, timeout=timeout,
                                      provider=provider, model=model,
                                      json_mode=True))
        except Exception as exc:
            LOG.warning(f"AI categorize batch {i // BATCH_CATEGORIZE} failed: {exc}")
            continue
        if not isinstance(parsed, dict):
            LOG.warning("AI categorize returned non-object JSON")
            continue
        for key in ("categories", "files", "result"):
            if isinstance(parsed.get(key), dict):
                parsed = parsed[key]
                break
        for name, cat in parsed.items():
            if name in batch and isinstance(cat, str) and cat in _CATEGORIES_JSON:
                result[name] = cat
            elif name in batch:
                LOG.debug(f"AI returned unknown category for {name}: {cat!r}")
    return result


def ai_organization_plan(api_key: str, files: List[dict[str, Any]],
                         timeout: int = 90, provider: str = "gemini",
                         model: Optional[str] = None) -> Dict[str, str]:
    if not files:
        return {}
    result: Dict[str, str] = {}
    for i in range(0, len(files), BATCH_PLAN):
        batch = files[i:i + BATCH_PLAN]
        sources = {str(f["source"]) for f in batch}
        prompt = (
            "You are organizing a Google Drive after a backup. For each "
            "source path, propose a tidy target path in a folder structure "
            "grouped by meaningful top-level folders (e.g. Work, Personal, "
            "Photos, Finance, Archives). Keep the exact filename and its "
            "extension unchanged. Use forward slashes. Return STRICT JSON "
            "only, an object mapping each exact source path to its target:\n"
            "{\"source/path.ext\": \"Work/Contracts/2026/name.ext\"}\n\n"
            f"FILES:\n{json.dumps(batch)}"
        )
        try:
            parsed = _parse_json(_ask(api_key, prompt, timeout=timeout,
                                      max_tokens=4000, provider=provider,
                                      model=model, json_mode=True))
        except Exception as exc:
            LOG.warning(f"AI plan batch {i // BATCH_PLAN} failed: {exc}")
            continue
        if not isinstance(parsed, dict):
            LOG.warning("AI plan returned non-object JSON")
            continue
        for key in ("targets", "plan", "result"):
            if isinstance(parsed.get(key), dict):
                parsed = parsed[key]
                break
        for source, target in parsed.items():
            if (source in sources and isinstance(target, str)
                    and target.strip() and "\\" not in target):
                result[source] = target.strip("/")
    return result


def ai_quality_check(api_key: str, analysis: dict[str, Any],
                     verify: Optional[dict[str, Any]] = None,
                     timeout: int = 60, provider: str = "gemini",
                     model: Optional[str] = None) -> List[dict[str, str]]:
    compact: dict[str, Any] = {
        "files": analysis.get("count", 0),
        "total_size_bytes": analysis.get("size", 0),
        "categories": {k: {"count": v["count"], "size": v["size"]}
                       for k, v in (analysis.get("categories") or {}).items()},
        "duplicate_groups": analysis.get("dup_count", 0),
        "duplicate_wasted_bytes": analysis.get("dup_wasted", 0),
        "junk_bytes": analysis.get("junk_size", 0),
        "junk_categories": list((analysis.get("junk") or {}).keys()),
        "empty_files": len(analysis.get("empty_files", [])),
        "verify": ({"status": "PASS" if verify.get("passed") else "FAIL",
                    "total": verify.get("total", 0),
                    "matched": verify.get("matched", 0),
                    "missing": verify.get("missing", 0),
                    "mismatch": verify.get("mismatch", 0),
                    "extra": verify.get("extra", 0)}
                   if verify else None),
    }
    prompt = (
        "You are reviewing a Google Drive backup analysis. Find real risks "
        "and concrete actions. Return STRICT JSON only: a list of up to 6 "
        "findings, each {\"severity\": \"high\"|\"medium\"|\"low\", "
        "\"message\": \"actionable sentence\"}. Examples: verify failed -> "
        "high; huge duplicate waste -> medium; no verification done -> "
        "medium; healthy -> one low finding saying the drive looks healthy.\n\n"
        f"DATA:\n{json.dumps(compact)}"
    )
    try:
        parsed = _parse_json(_ask(api_key, prompt, timeout=timeout,
                                  provider=provider, model=model,
                                  json_mode=True))
    except Exception as exc:
        LOG.warning(f"AI quality check failed: {exc}")
        return []
    if not isinstance(parsed, list):
        if isinstance(parsed, dict):
            for key in ("findings", "issues", "result"):
                if isinstance(parsed.get(key), list):
                    parsed = parsed[key]
                    break
        if not isinstance(parsed, list):
            LOG.warning("AI quality check returned non-list JSON")
            return []
    findings: List[dict[str, str]] = []
    for item in parsed:
        if (isinstance(item, dict) and item.get("severity") in
                ("high", "medium", "low") and isinstance(item.get("message"), str)
                and item["message"].strip()):
            findings.append({"severity": item["severity"],
                             "message": item["message"].strip()})
    return findings


_CATEGORIES_JSON: Tuple[str, ...] = (
    "Images", "Videos", "Audio", "Documents", "Spreadsheets",
    "Presentations", "Archives", "Code", "Installers", "3D & Design",
    "Other",
)
