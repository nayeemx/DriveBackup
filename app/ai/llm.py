import json

import requests

from ..utils.logging_utils import get_logger

LOG = get_logger()

MODEL = "gemini-2.5-flash"
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_DEFAULT_MODEL = "openrouter/auto"

BATCH_CATEGORIZE = 200
BATCH_PLAN = 100


def _ask(api_key, prompt, timeout=60, max_tokens=2000,
         provider="gemini", model=None, json_mode=False):
    if not api_key:
        raise RuntimeError("No API key configured (free Gemini key from "
                           "Google AI Studio, or an OpenRouter key - "
                           "no credit card needed for Gemini).")
    if provider == "openrouter":
        payload = {
            "model": model or OPENROUTER_DEFAULT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
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
        content = data["choices"][0]["message"].get("content")
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
    resp = requests.post(
        API.format(model=model or MODEL),
        params={"key": api_key},
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def summarize(api_key: str, data: dict, timeout=60,
              provider="gemini", model=None) -> str:
    """Executive summary of the analysis. Returns markdown text."""
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


def ai_categorize(api_key: str, names, timeout=60,
                  provider="gemini", model=None):
    """Classify filenames the extension rules could not.

    Returns {name: category} using only the known categories, or {} on
    any failure (callers fall back to rule-based results).
    """
    if not names:
        return {}
    names = list(dict.fromkeys(str(n) for n in names))
    result = {}
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


def ai_organization_plan(api_key: str, files, timeout=90,
                         provider="gemini", model=None):
    """AI-proposed target paths for an organization plan.

    Returns {source: target} where target keeps the original extension.
    Invalid entries are dropped (caller falls back to rules per file).
    """
    if not files:
        return {}
    result = {}
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


def ai_quality_check(api_key: str, analysis: dict, verify=None, timeout=60,
                     provider="gemini", model=None):
    """AI review of the drive health summary.

    Returns a list of findings {"severity": high|medium|low, "message": str}.
    Empty list on failure (never blocks the pipeline).
    """
    compact = {
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
    findings = []
    for item in parsed:
        if (isinstance(item, dict) and item.get("severity") in
                ("high", "medium", "low") and isinstance(item.get("message"), str)
                and item["message"].strip()):
            findings.append({"severity": item["severity"],
                             "message": item["message"].strip()})
    return findings


_CATEGORIES_JSON = (
    "Images", "Videos", "Audio", "Documents", "Spreadsheets",
    "Presentations", "Archives", "Code", "Installers", "3D & Design",
    "Other",
)