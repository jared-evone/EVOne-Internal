from datetime import datetime, timezone

from services.supabase_client import supabase_admin

_SCHEMA = "evone_billing"


def list_suppliers() -> list:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("suppliers")
        .select("*")
        .order("name")
        .execute()
    )
    return res.data or []


def create_supplier(payload: dict) -> dict:
    res = supabase_admin.schema(_SCHEMA).table("suppliers").insert(payload).execute()
    return res.data[0] if res.data else {}


def get_supplier(supplier_id: str) -> dict | None:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("suppliers")
        .select("*")
        .eq("id", supplier_id)
        .execute()
    )
    return res.data[0] if res.data else None


def update_supplier(supplier_id: str, payload: dict) -> dict:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("suppliers")
        .update(payload)
        .eq("id", supplier_id)
        .execute()
    )
    return res.data[0] if res.data else {}


def delete_supplier(supplier_id: str) -> dict:
    supabase_admin.schema(_SCHEMA).table("suppliers").delete().eq("id", supplier_id).execute()
    return {"success": True}
