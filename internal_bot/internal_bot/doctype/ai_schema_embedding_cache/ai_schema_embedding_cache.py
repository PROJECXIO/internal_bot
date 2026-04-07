import frappe
from frappe.model.document import Document


class AISchemaEmbeddingCache(Document):
	# begin: auto-generated types
	from frappe.types import DF

	cache_key: DF.Data
	doctype_name: DF.Data
	embedding_model: DF.Data | None
	embedding_type: DF.Literal["fields", "corpus"]
	embeddings_json: DF.LongText | None
	fingerprint: DF.Data | None
	provider: DF.Data | None
	# end: auto-generated types
	pass
