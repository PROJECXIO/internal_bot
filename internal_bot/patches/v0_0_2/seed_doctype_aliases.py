"""
Seed multilingual aliases for common ERP DocTypes.
"""
import frappe

from internal_bot.bot.services.doctype_aliases import invalidate_alias_cache

_ALIASES = {
    "Sales Invoice": {
        "en": ["sales invoice", "sales bill", "customer invoice"],
        "ar": ["فاتورة مبيعات", "فواتير مبيعات", "فاتورة بيع", "فواتير"],
    },
    "Purchase Invoice": {
        "en": ["purchase invoice", "supplier invoice", "vendor bill"],
        "ar": ["فاتورة شراء", "فواتير شراء", "فاتورة مورد", "فواتير"],
    },
    "Customer": {
        "en": ["customer", "customers", "client", "clients"],
        "ar": ["عميل", "عملاء", "العملاء"],
    },
    "Supplier": {
        "en": ["supplier", "suppliers", "vendor", "vendors"],
        "ar": ["مورد", "موردين", "موردون", "الموردين"],
    },
    "Item": {
        "en": ["item", "items", "product", "products"],
        "ar": ["صنف", "اصناف", "أصناف", "منتج", "منتجات"],
    },
    "Sales Order": {
        "en": ["sales order", "sales orders", "customer order"],
        "ar": ["امر بيع", "أمر بيع", "اوامر بيع", "أوامر بيع"],
    },
    "Purchase Order": {
        "en": ["purchase order", "purchase orders", "supplier order"],
        "ar": ["امر شراء", "أمر شراء", "اوامر شراء", "أوامر شراء"],
    },
    "Delivery Note": {
        "en": ["delivery note", "delivery notes", "shipment", "shipments"],
        "ar": ["اذن تسليم", "إذن تسليم", "اذون تسليم", "شحنة", "شحنات"],
    },
    "Purchase Receipt": {
        "en": ["purchase receipt", "purchase receipts", "goods receipt"],
        "ar": ["استلام شراء", "استلامات شراء", "استلام بضاعة", "استلام بضائع"],
    },
    "Stock Entry": {
        "en": ["stock entry", "stock entries", "inventory movement"],
        "ar": ["قيد مخزون", "قيود مخزون", "حركة مخزون", "حركات مخزون"],
    },
    "Journal Entry": {
        "en": ["journal entry", "journal entries", "accounting entry"],
        "ar": ["قيد يومية", "قيود يومية", "قيد محاسبي", "قيود محاسبية"],
    },
    "Payment Entry": {
        "en": ["payment entry", "payment entries", "payment", "payments"],
        "ar": ["قيد دفع", "قيود دفع", "دفعة", "دفعات", "مدفوعات"],
    },
    "Quotation": {
        "en": ["quotation", "quotations", "quote", "quotes"],
        "ar": ["عرض سعر", "عروض اسعار", "عروض أسعار"],
    },
    "Material Request": {
        "en": ["material request", "material requests", "purchase request"],
        "ar": ["طلب مواد", "طلبات مواد", "طلب مشتريات", "طلبات مشتريات"],
    },
    "BOM": {
        "en": ["bom", "bill of materials"],
        "ar": ["قائمة مواد", "هيكل منتج", "وصفة تصنيع"],
    },
    "Work Order": {
        "en": ["work order", "work orders", "production order"],
        "ar": ["امر عمل", "أمر عمل", "اوامر عمل", "أوامر عمل", "امر انتاج", "أمر إنتاج"],
    },
    "Lead": {
        "en": ["lead", "leads", "prospect", "prospects"],
        "ar": ["عميل محتمل", "عملاء محتملون", "ليد"],
    },
    "Opportunity": {
        "en": ["opportunity", "opportunities", "sales opportunity"],
        "ar": ["فرصة", "فرص", "فرصة بيع", "فرص بيع"],
    },
}


def execute():
    for doctype_name, languages in _ALIASES.items():
        if not frappe.db.exists("DocType", doctype_name):
            continue

        for language, aliases in languages.items():
            for alias in aliases:
                if frappe.db.exists(
                    "AI DocType Alias",
                    {"doctype_name": doctype_name, "alias": alias},
                ):
                    continue

                frappe.get_doc(
                    {
                        "doctype": "AI DocType Alias",
                        "doctype_name": doctype_name,
                        "alias": alias,
                        "language": language,
                    }
                ).insert(ignore_permissions=True)

    invalidate_alias_cache()
