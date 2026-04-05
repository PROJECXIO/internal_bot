"""
LLM client abstraction.

Wraps the openai SDK directly (already installed in bench venv at openai 2.x).
Do NOT use langchain-openai — it may conflict with the installed openai version.

A new LLMClient instance must be created per request by reading
AI Provider Settings at call time.  Never cache as a module-level singleton
because Frappe workers serve multiple sites and settings differ per site.
"""
import os

import frappe

_EMBEDDING_MODELS: dict[str, str | None] = {
	"OpenAI": "text-embedding-3-small",
	"Azure OpenAI": "text-embedding-3-small",
	"OpenRouter": "openai/text-embedding-3-small",
	"Anthropic": None,
}


class LLMClient:
	def __init__(
		self,
		provider: str,
		model: str,
		embedding_model: str | None,
		api_key: str,
		api_base: str | None = None,
		api_version: str | None = None,
		max_tokens: int = 2000,
		temperature: float = 0.0,
		request_timeout: int = 30,
	):
		self.provider = provider
		self.model = model
		self.max_tokens = max_tokens
		self.temperature = temperature
		self.request_timeout = request_timeout
		self.last_input_tokens = 0
		self.last_output_tokens = 0
		self.embedding_model = embedding_model or _EMBEDDING_MODELS.get(provider)
		self._client = self._build_client(provider, api_key, api_base, api_version)
		self._langsmith_wrapped = bool(
			getattr(self._client, "_internal_bot_langsmith_wrapped", False)
		)

	# ------------------------------------------------------------------
	# Public interface
	# ------------------------------------------------------------------

	def chat_completion(
		self,
		messages: list[dict],
		temperature: float | None = None,
		max_tokens: int | None = None,
		trace_metadata: dict | None = None,
		trace_tags: list[str] | None = None,
	) -> str:
		"""
		Send a chat completion request.  Returns the assistant message string.
		Raises an exception on network/API errors (caller handles retries).
		"""
		temp = temperature if temperature is not None else self.temperature
		tokens = max_tokens if max_tokens is not None else self.max_tokens

		request_kwargs = {}
		if self._langsmith_wrapped and (trace_metadata or trace_tags):
			request_kwargs["langsmith_extra"] = {
				k: v
				for k, v in {
					"metadata": trace_metadata,
					"tags": trace_tags,
				}.items()
				if v
			}

		response = self._client.chat.completions.create(
			model=self.model,
			messages=messages,
			temperature=temp,
			max_tokens=tokens,
			timeout=self.request_timeout,
			**request_kwargs,
		)

		choice = response.choices[0]
		content = choice.message.content or ""

		# Attach token usage to this instance for the caller to read
		usage = response.usage
		self.last_input_tokens = usage.prompt_tokens if usage else 0
		self.last_output_tokens = usage.completion_tokens if usage else 0

		return content

	def create_embeddings(self, texts: list[str]) -> list[list[float]] | None:
		"""
		Return embeddings for the supplied texts, or None on unsupported providers/failure.
		"""
		model = self.embedding_model
		if not model or not texts:
			return None

		try:
			all_embeddings = []
			for index in range(0, len(texts), 100):
				batch = texts[index : index + 100]
				response = self._client.embeddings.create(
					model=model,
					input=batch,
					timeout=self.request_timeout,
				)
				sorted_data = sorted(response.data, key=lambda item: item.index)
				all_embeddings.extend([item.embedding for item in sorted_data])
			return all_embeddings
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Internal Bot: embeddings call failed")
			return None

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _build_client(provider: str, api_key: str, api_base: str | None, api_version: str | None):
		try:
			import openai
		except ImportError:
			frappe.throw("openai package is not installed. Run: bench pip install openai")

		if provider == "Azure OpenAI":
			client = openai.AzureOpenAI(
				api_key=api_key,
				azure_endpoint=api_base or "",
				api_version=api_version or "2024-02-01",
			)
			return LLMClient._maybe_wrap_with_langsmith(client, provider)

		if provider == "OpenRouter":
			client = openai.OpenAI(
				api_key=api_key,
				base_url=api_base or "https://openrouter.ai/api/v1",
			)
			return LLMClient._maybe_wrap_with_langsmith(client, provider)

		# OpenAI or Anthropic (via openai-compatible endpoint)
		kwargs = {"api_key": api_key}
		if api_base:
			kwargs["base_url"] = api_base
		client = openai.OpenAI(**kwargs)
		return LLMClient._maybe_wrap_with_langsmith(client, provider)

	@staticmethod
	def _maybe_wrap_with_langsmith(client, provider: str):
		if not _langsmith_tracing_enabled():
			return client

		try:
			from langsmith.wrappers import wrap_openai
		except ImportError:
			return client

		try:
			wrapped = wrap_openai(
				client,
				tracing_extra={
					"tags": ["internal_bot", "openai-client"],
					"metadata": {
						"app": "internal_bot",
						"provider": provider,
					},
				},
				chat_name="InternalBotChatCompletion",
				completions_name="InternalBotCompletion",
			)
			setattr(wrapped, "_internal_bot_langsmith_wrapped", True)
			return wrapped
		except Exception as exc:
			frappe.log_error(message=str(exc), title="Internal Bot: LangSmith client wrap failed")
			return client


def get_llm_client() -> LLMClient:
	"""
	Factory: reads AI Provider Settings and returns a configured LLMClient.
	Call this once per request at graph entry.
	"""
	settings = frappe.get_doc("AI Provider Settings")
	return LLMClient(
		provider=settings.provider,
		model=settings.model,
		embedding_model=getattr(settings, "embedding_model", None) or None,
		api_key=settings.get_password("api_key"),
		api_base=settings.api_base or None,
		api_version=settings.api_version or None,
		max_tokens=settings.max_tokens or 2000,
		temperature=settings.temperature or 0.0,
		request_timeout=settings.request_timeout or 30,
	)


def _langsmith_tracing_enabled() -> bool:
	return (os.getenv("LANGSMITH_TRACING") or "").strip().lower() in {"1", "true", "yes", "on"} or (
		os.getenv("LANGCHAIN_TRACING_V2") or ""
	).strip().lower() in {"1", "true", "yes", "on"}
