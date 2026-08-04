from __future__ import annotations

import json
import os

import httpx

from c4core import canonical_json

from .gemini import agent_response_model, prepare_agent_prompt, restore_evidence_aliases, sanitize_agent_fragment
from .models import AgentGraphFragment, AgentRole
from .orchestration import AgentRequest, RetrievalTool


_DESCRIPTION_LENGTH_ERROR = "every element description must contain at least eight characters"


def _repair_short_descriptions(fragment: AgentGraphFragment) -> AgentGraphFragment:
    repaired = tuple(
        element.model_copy(update={
            "description": f"Responsabilidades arquitectónicas representadas por {element.name}.",
        })
        if len(element.description.strip()) < 8
        else element
        for element in fragment.elements
    )
    return fragment.model_copy(update={"elements": repaired})


class OllamaC4Agent:
    """Local schema-constrained implementation of both C4 agent protocols."""

    prompt_version = "semantic-agent-v13"

    def __init__(
        self,
        role: AgentRole,
        module_id: str | None = None,
        *,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.role = role
        self.module_id = module_id
        self.model = model or os.getenv("C4_OLLAMA_MODEL", "qwen3:8b")
        self.base_url = (base_url or os.getenv("C4_OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")

    def analyze_infrastructure(self, request: AgentRequest, retrieve: RetrievalTool) -> AgentGraphFragment:
        return self._analyze(request, retrieve)

    def analyze_module(self, request: AgentRequest, retrieve: RetrievalTool) -> AgentGraphFragment:
        return self._analyze(request, retrieve)

    def _analyze(self, request: AgentRequest, retrieve: RetrievalTool) -> AgentGraphFragment:
        prompt, schema, evidence_id_by_alias = prepare_agent_prompt(
            self.role, self.module_id, self.model, "ollama", request, retrieve
        )
        timeout = float(os.getenv("C4_OLLAMA_TIMEOUT_SECONDS", "1800"))
        attempts = max(1, int(os.getenv("C4_OLLAMA_AGENT_ATTEMPTS", "2")))
        validation_error = ""
        for attempt in range(1, attempts + 1):
            messages = [{"role": "user", "content": prompt}]
            if validation_error:
                messages.append({
                    "role": "user",
                    "content": "Correct the previous response and return the complete JSON again. " + validation_error,
                })
            try:
                response = httpx.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "think": False,
                        "format": schema,
                        "options": {
                            "temperature": 0,
                            "num_ctx": int(os.getenv("C4_OLLAMA_CONTEXT_TOKENS", "16384")),
                            "num_predict": int(os.getenv("C4_OLLAMA_MAX_OUTPUT_TOKENS", "4096")),
                        },
                        "keep_alive": os.getenv("C4_OLLAMA_KEEP_ALIVE", "10m"),
                    },
                    timeout=timeout,
                )
            except httpx.TransportError as error:
                if attempt == attempts:
                    raise RuntimeError(
                        f"Ollama transport failed after {attempts} attempts: {type(error).__name__}: {error}"
                    ) from error
                continue
            response.raise_for_status()
            body = response.json()
            content = body.get("message", {}).get("content")
            if not isinstance(content, str) or not content.strip():
                validation_error = "The response was empty."
                continue
            try:
                raw_fragment = json.loads(content)
                fragment = agent_response_model(self.role).model_validate_json(canonical_json(
                    restore_evidence_aliases(raw_fragment, evidence_id_by_alias)
                ))
            except (ValueError, json.JSONDecodeError) as error:
                validation_error = f"The response was invalid JSON or violated the schema: {error}"
                continue
            maximum_elements = 2
            invalid = []
            if len(fragment.elements) > maximum_elements:
                invalid.append(f"return at most {maximum_elements} elements")
            if any(len(item.name.strip()) < 3 for item in fragment.elements):
                invalid.append("every element name must contain at least three characters")
            if any(len(item.description.strip()) < 8 for item in fragment.elements):
                invalid.append(_DESCRIPTION_LENGTH_ERROR)
            element_ids = [item.local_id for item in fragment.elements]
            if len(element_ids) != len(set(element_ids)):
                invalid.append("every element local_id must be unique within the fragment")
            relationship_ids = [item.local_id for item in fragment.relationships]
            if len(relationship_ids) != len(set(relationship_ids)):
                invalid.append("every relationship local_id must be unique within the fragment")
            if any(
                len(item.evidence_chunk_ids) > 5 or len(set(item.evidence_chunk_ids)) != len(item.evidence_chunk_ids)
                for item in (*fragment.elements, *fragment.relationships)
            ):
                invalid.append("every candidate must cite at most five unique evidence aliases")
            if not invalid:
                return sanitize_agent_fragment(fragment, request.architecture_references)
            if (
                attempt == attempts
                and set(invalid) == {_DESCRIPTION_LENGTH_ERROR}
            ):
                fragment = _repair_short_descriptions(fragment)
                return sanitize_agent_fragment(fragment, request.architecture_references)
            validation_error = "Fix these validation errors: " + "; ".join(invalid) + "."
        raise RuntimeError(f"Ollama agent response failed validation after {attempts} attempts: {validation_error}")
