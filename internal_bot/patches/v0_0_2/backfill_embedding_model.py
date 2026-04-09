"""
Patch: populate the new embedding_model field on AI Provider Settings.
"""
import frappe

_DEFAULT_EMBEDDING_MODELS = {
	"OpenAI": "text-embedding-3-small",
	"Azure OpenAI": "text-embedding-3-small",
	"OpenRouter": "openai/text-embedding-3-small",
	"Anthropic": "",
}


def execute():
	provider = frappe.db.get_single_value("AI Provider Settings", "provider")
	current_embedding_model = frappe.db.get_single_value("AI Provider Settings", "embedding_model")
	if current_embedding_model is not None and str(current_embedding_model).strip():
		return

	default_model = _DEFAULT_EMBEDDING_MODELS.get(provider or "", "")
	if default_model:
		frappe.db.set_single_value("AI Provider Settings", "embedding_model", default_model)
		frappe.db.commit()
