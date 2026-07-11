from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings
from serving.types import Instance


class VLLMClient:
    """Thin async client over an OpenAI-compatible model API (task 7.1).

    One client instance targets one server (one model replica). Works against a local
    vLLM server or a remote hosted API; the API key (when set and not the "EMPTY"
    placeholder) is sent as an Authorization: Bearer header on every request.
    """

    def __init__(self, timeout: float = 30.0, api_key: str | None = None) -> None:
        if api_key is None:
            api_key = get_settings().llm_api_key
        headers = {}
        if api_key and api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=0.2, max=2))
    async def generate(self, instance: Instance, model: str, prompt: str, max_tokens: int) -> str:
        resp = await self._client.post(
            f"{instance.endpoint}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.2,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def health(self, instance: Instance) -> bool:
        try:
            resp = await self._client.get(f"{instance.endpoint}/v1/models")
            return resp.status_code == 200
        except Exception:
            return False

    async def metrics(self, instance: Instance) -> dict:
        """No-op for a hosted OpenAI API: there is no server-side /metrics endpoint,
        so the autoscaler relies on request-side signals (pending_tokens/inflight)."""
        return {}

    async def aclose(self) -> None:
        await self._client.aclose()
