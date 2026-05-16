import os

import httpx
import structlog

logger = structlog.get_logger()

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")
AI_TIMEOUT = int(os.environ.get("AI_TIMEOUT_SECONDS", "30"))


def chat(prompt: str, system: str) -> str:
    """Send a prompt to Ollama and return the raw text response."""
    url = f"{OLLAMA_HOST}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": "json",
    }

    logger.info("ollama_request", model=OLLAMA_MODEL, host=OLLAMA_HOST)

    try:
        with httpx.Client(timeout=AI_TIMEOUT) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            content = data["message"]["content"]
            logger.info("ollama_response_ok", length=len(content))
            return content
    except httpx.TimeoutException:
        logger.error("ollama_timeout", timeout=AI_TIMEOUT)
        raise
    except httpx.HTTPStatusError as exc:
        logger.error(
            "ollama_http_error",
            status=exc.response.status_code,
            body=exc.response.text[:200],
        )
        raise
    except KeyError as exc:
        logger.error("ollama_unexpected_response", error=str(exc))
        raise RuntimeError(f"Unexpected Ollama response format: {exc}") from exc
