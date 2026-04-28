"""
Llama Stack LLM client wrapper — SHELL ONLY for Phase 0.
No agents are implemented yet; that is Phase 1C.

Uses the OpenAI Python SDK pointed at the OCI Llama Stack endpoint.
Rationale: The Llama Stack exposes an OpenAI-compatible surface
(/v1/chat/completions, /v1/embeddings, etc.) and the openai SDK
handles streaming, retries, and structured output natively. Using
the SDK saves us from writing our own streaming parser and retry logic
vs raw httpx calls.

Auth: instance principal from this OCI VM — no API key needed.
Endpoint: https://llama-stack.ai-apps-ord.oci-incubations.com
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)

# Default Llama Stack endpoint (per 00-DECISIONS-AND-CONSTRAINTS.md §4.2)
DEFAULT_ENDPOINT = "https://llama-stack.ai-apps-ord.oci-incubations.com"

# Model picks per role (per §4.2 locked model table)
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
    """
    Thin wrapper around the OCI Llama Stack OpenAI-compatible API.

    Phase 0: method signatures only. Actual agent implementations
    are in Phase 1C. The health check is functional to verify
    connectivity on startup.
    """

    def __init__(self, base_url: str = DEFAULT_ENDPOINT):
        self.base_url = base_url.rstrip("/")
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
                # No API key — instance principal auth from OCI VM
            )
        return self._http_client

    async def health_check(self) -> dict:
        """
        Verify Llama Stack is reachable. Called on startup.
        Returns {"status": "ok"} or {"status": "unreachable", "error": "..."}.
        """
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

    async def extract(
        self,
        *,
        model: str = MODELS["extraction"],
        prompt_version: str,
        input_text: str,
        schema: Optional[dict] = None,
    ) -> ExtractionResult:
        """
        Single-turn structured extraction (e.g. EDGAR 8-K extractor).
        Phase 1C will implement; Phase 0 raises NotImplementedError.
        """
        raise NotImplementedError(
            "LlmClient.extract() is a Phase 1C deliverable. "
            "See backend/llm/agents/edgar_extractor.py"
        )

    async def reason(
        self,
        *,
        model: str = MODELS["reasoning"],
        prompt_version: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> AgentTurn:
        """
        Multi-turn agent reasoning with tool-use (e.g. LLC resolver).
        Phase 1C will implement; Phase 0 raises NotImplementedError.
        """
        raise NotImplementedError(
            "LlmClient.reason() is a Phase 1C deliverable. "
            "See backend/llm/agents/llc_resolver.py"
        )

    async def chat_stream(
        self,
        *,
        model: str = MODELS["reasoning"],
        conversation_id: Optional[str] = None,
        message: str,
        tools: Optional[list[dict]] = None,
    ) -> AsyncIterator[ChatChunk]:
        """
        Streaming conversational chat (e.g. Triangulation Q&A agent).
        Phase 1C will implement; Phase 0 raises NotImplementedError.
        """
        raise NotImplementedError(
            "LlmClient.chat_stream() is a Phase 1C deliverable. "
            "See backend/llm/agents/qa_agent.py"
        )
        # Make this an async generator to satisfy the type signature
        yield ChatChunk(delta="", done=True)  # pragma: no cover

    async def embed(
        self,
        *,
        model: str = MODELS["embedding"],
        texts: list[str],
    ) -> list[list[float]]:
        """
        Text embedding (e.g. for vector search over permit narratives).
        Phase 1C will implement; Phase 0 raises NotImplementedError.
        """
        raise NotImplementedError(
            "LlmClient.embed() is a Phase 1C deliverable. "
            "See backend/llm/tools/vector_search.py"
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.close()

    @staticmethod
    def compute_input_hash(text: str) -> str:
        """SHA-256 hash for caching + idempotency."""
        return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"


# Module-level singleton — importable by agents in Phase 1C
llm_client = LlmClient()
