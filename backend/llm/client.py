"""
Llama Stack LLM client wrapper -- Phase 1C implementation.

Real httpx async calls against the OCI Llama Stack OpenAI-compatible API.

Auth: instance principal from this OCI VM -- no API key needed.
Endpoint: https://llama-stack.ai-apps-ord.oci-incubations.com

NOTE on token parameter naming:
    The GPT-5.x family rejects `max_tokens` and requires `max_completion_tokens`.
    We always use `max_completion_tokens` for chat/completions calls.
    The /v1/embeddings endpoint is unaffected (no completion-token parameter).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)

# Default Llama Stack endpoint (per 00-DECISIONS-AND-CONSTRAINTS.md section 4.2)
DEFAULT_ENDPOINT = "https://llama-stack.ai-apps-ord.oci-incubations.com"

# Model picks per role (per section 4.2 locked model table)
MODELS = {
    "extraction": "oci/openai.gpt-5.4-mini",
    "extraction_fallback": "oci/google.gemini-2.5-flash",
    "reasoning": "oci/openai.gpt-5.4",
    "reasoning_fallback": "oci/xai.grok-4.20-reasoning",
    "vision": "oci/google.gemini-2.5-pro",
    "vision_fallback": "oci/cohere.command-a-vision",
    "embedding": "oci/openai.text-embedding-3-large",
    "embedding_fallback": "oci/cohere.embed-english-v3.0",
}


@dataclass
class ExtractionResult:
    """Result from a single-turn structured extraction."""
    result: dict
    model: str
    prompt_version: str
    input_hash: str
    confidence: float
    latency_ms: int
    tokens: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


@dataclass
class AgentTurn:
    """Result from a multi-turn reasoning call."""
    content: str
    model: str
    prompt_version: str
    tool_calls: list = field(default_factory=list)
    confidence: float = 0.0
    latency_ms: int = 0
    tokens: dict = field(default_factory=dict)


@dataclass
class ChatChunk:
    """A single chunk from a streaming chat response."""
    delta: str
    tool_call: Optional[dict] = None
    done: bool = False


class LlmClient:
    """Thin async wrapper around the OCI Llama Stack OpenAI-compatible API."""

    def __init__(self, base_url: str = DEFAULT_ENDPOINT):
        self.base_url = base_url.rstrip("/")
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
                # No API key -- instance principal auth from OCI VM
            )
        return self._http_client

    async def health_check(self) -> dict:
        """Verify Llama Stack is reachable. Called on startup."""
        try:
            client = await self._get_client()
            resp = await client.get("/v1/health")
            if resp.status_code == 200:
                logger.info("llama_stack.health_ok", extra={"url": self.base_url})
                return {"status": "ok"}
            else:
                logger.warning(
                    "llama_stack.health_unexpected_status",
                    extra={"status_code": resp.status_code, "body": resp.text[:200]},
                )
                return {"status": "degraded", "error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            logger.error(
                "llama_stack.health_unreachable",
                extra={"url": self.base_url, "error": str(exc)},
            )
            return {"status": "unreachable", "error": str(exc)}

    # ------------------------------------------------------------------
    # extract -- single-turn structured JSON extraction
    # ------------------------------------------------------------------
    async def extract(
        self,
        *,
        model: str = MODELS["extraction"],
        prompt_version: str,
        input_text: str,
        schema: Optional[dict] = None,
    ) -> ExtractionResult:
        """Single-turn structured extraction (e.g. EDGAR 8-K extractor)."""
        client = await self._get_client()
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a precise data extractor. Reply with JSON only "
                        "matching the provided schema."
                    ),
                },
                {"role": "user", "content": input_text},
            ],
            "max_completion_tokens": 2048,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "extraction",
                    "strict": True,
                    "schema": schema,
                },
            }

        input_hash = self.compute_input_hash(input_text)
        t0 = time.monotonic()
        try:
            resp = await client.post("/v1/chat/completions", json=body)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error(
                "llm.extract_http_error",
                extra={"model": model, "prompt_version": prompt_version, "error": str(exc)},
            )
            raise

        latency_ms = int((time.monotonic() - t0) * 1000)
        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "") or ""
        )
        usage = data.get("usage", {}) or {}
        tokens = {
            "prompt": usage.get("prompt_tokens", 0),
            "completion": usage.get("completion_tokens", 0),
            "total": usage.get("total_tokens", 0),
        }

        # Try to parse JSON content
        result_obj: dict = {}
        errors: list = []
        confidence = 0.0
        try:
            result_obj = json.loads(content) if content else {}
            confidence = 0.85
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append({"type": "json_decode", "msg": str(exc), "raw": content[:200]})
            confidence = 0.0

        return ExtractionResult(
            result=result_obj,
            model=model,
            prompt_version=prompt_version,
            input_hash=input_hash,
            confidence=confidence,
            latency_ms=latency_ms,
            tokens=tokens,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # reason -- multi-turn reasoning with optional tool-use
    # ------------------------------------------------------------------
    async def reason(
        self,
        *,
        model: str = MODELS["reasoning"],
        prompt_version: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> AgentTurn:
        """Multi-turn agent reasoning with optional tool-use."""
        client = await self._get_client()
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": 4096,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        t0 = time.monotonic()
        try:
            resp = await client.post("/v1/chat/completions", json=body)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error(
                "llm.reason_http_error",
                extra={"model": model, "prompt_version": prompt_version, "error": str(exc)},
            )
            raise

        latency_ms = int((time.monotonic() - t0) * 1000)
        data = resp.json()
        msg = data.get("choices", [{}])[0].get("message", {}) or {}
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []
        usage = data.get("usage", {}) or {}
        tokens = {
            "prompt": usage.get("prompt_tokens", 0),
            "completion": usage.get("completion_tokens", 0),
            "total": usage.get("total_tokens", 0),
        }

        return AgentTurn(
            content=content,
            model=model,
            prompt_version=prompt_version,
            tool_calls=tool_calls,
            confidence=0.0,
            latency_ms=latency_ms,
            tokens=tokens,
        )

    # ------------------------------------------------------------------
    # chat_stream -- async generator over SSE chunks
    # ------------------------------------------------------------------
    async def chat_stream(
        self,
        *,
        model: str = MODELS["reasoning"],
        conversation_id: Optional[str] = None,
        message: str,
        tools: Optional[list[dict]] = None,
    ) -> AsyncIterator[ChatChunk]:
        """Streaming conversational chat. Yields ChatChunk per delta."""
        client = await self._get_client()
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": message}],
            "stream": True,
            "max_completion_tokens": 4096,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        try:
            async with client.stream(
                "POST", "/v1/chat/completions", json=body
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data: "):
                        continue
                    payload_str = line[len("data: "):].strip()
                    if payload_str == "[DONE]":
                        yield ChatChunk(delta="", done=True)
                        return
                    try:
                        payload = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue
                    choices = payload.get("choices") or [{}]
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    tool_calls = delta.get("tool_calls") or []
                    first_tc = tool_calls[0] if tool_calls else None
                    yield ChatChunk(delta=content or "", tool_call=first_tc)
        except httpx.HTTPError as exc:
            logger.error(
                "llm.chat_stream_http_error",
                extra={"model": model, "error": str(exc)},
            )
            raise

    # ------------------------------------------------------------------
    # embed -- text embeddings
    # ------------------------------------------------------------------
    async def embed(
        self,
        *,
        model: str = MODELS["embedding"],
        texts: list[str],
    ) -> list[list[float]]:
        """Text embedding."""
        client = await self._get_client()
        try:
            resp = await client.post(
                "/v1/embeddings",
                json={"model": model, "input": texts},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error(
                "llm.embed_http_error",
                extra={"model": model, "error": str(exc)},
            )
            raise
        data = resp.json()
        return [d["embedding"] for d in data.get("data", [])]

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    @staticmethod
    def compute_input_hash(text: str) -> str:
        """SHA-256 hash for caching + idempotency."""
        return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"


# Module-level singleton -- importable by agents
llm_client = LlmClient()
