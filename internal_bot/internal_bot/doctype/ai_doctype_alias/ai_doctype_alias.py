import frappe
from frappe.model.document import Document


class AIDocTypeAlias(Document):
	# begin: auto-generated types
	from frappe.types import DF

	alias: DF.Data
	doctype_name: DF.Link
	language: DF.Literal["ar", "en"]
	# end: auto-generated types

	def on_update(self):
		_invalidate_alias_cache()

	def on_trash(self):
		_invalidate_alias_cache()


def _invalidate_alias_cache():
	from internal_bot.bot.services.doctype_aliases import invalidate_alias_cache

	invalidate_alias_cache()
