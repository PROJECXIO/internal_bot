"""
LLM client abstraction.

Wraps the openai SDK directly (already installed in bench venv at openai 2.x).
Do NOT use langchain-openai — it may conflict with the installed openai version.

A new LLMClient instance must be created per request by reading
AI Provider Settings at call time.  Never cache as a module-level singleton
because Frappe workers serve multiple sites and settings differ per site.
"""
import frappe


class LLMClient:
	def __init__(
		self,
		provider: str,
		model: str,
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
		self._client = self._build_client(provider, api_key, api_base, api_version)

	# ------------------------------------------------------------------
	# Public interface
	# ------------------------------------------------------------------

	def chat_completion(
		self,
		messages: list[dict],
		temperature: float | None = None,
		max_tokens: int | None = None,
	) -> str:
		"""
		Send a chat completion request.  Returns the assistant message string.
		Raises an exception on network/API errors (caller handles retries).
		"""
		temp = temperature if temperature is not None else self.temperature
		tokens = max_tokens if max_tokens is not None else self.max_tokens

		response = self._client.chat.completions.create(
			model=self.model,
			messages=messages,
			temperature=temp,
			max_tokens=tokens,
			timeout=self.request_timeout,
		)

		choice = response.choices[0]
		content = choice.message.content or ""

		# Attach token usage to this instance for the caller to read
		usage = response.usage
		self.last_input_tokens = usage.prompt_tokens if usage else 0
		self.last_output_tokens = usage.completion_tokens if usage else 0

		return content

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
			return openai.AzureOpenAI(
				api_key=api_key,
				azure_endpoint=api_base or "",
				api_version=api_version or "2024-02-01",
			)

		if provider == "OpenRouter":
			return openai.OpenAI(
				api_key=api_key,
				base_url=api_base or "https://openrouter.ai/api/v1",
			)

		# OpenAI or Anthropic (via openai-compatible endpoint)
		kwargs = {"api_key": api_key}
		if api_base:
			kwargs["base_url"] = api_base
		return openai.OpenAI(**kwargs)


def get_llm_client() -> LLMClient:
	"""
	Factory: reads AI Provider Settings and returns a configured LLMClient.
	Call this once per request at graph entry.
	"""
	settings = frappe.get_doc("AI Provider Settings")
	return LLMClient(
		provider=settings.provider,
		model=settings.model,
		api_key=settings.get_password("api_key"),
		api_base=settings.api_base or None,
		api_version=settings.api_version or None,
		max_tokens=settings.max_tokens or 2000,
		temperature=settings.temperature or 0.0,
		request_timeout=settings.request_timeout or 30,
	)
