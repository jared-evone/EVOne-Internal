from datetime import datetime, timezone

from services.supabase_client import supabase_admin

_SCHEMA = "evone_billing"


def list_customers() -> list:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("customers")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def create_customer(payload: dict) -> dict:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("customers")
        .insert(payload)
        .execute()
    )
    return res.data[0] if res.data else {}


def get_customer(customer_id: str) -> dict | None:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("customers")
        .select("*")
        .eq("id", customer_id)
        .execute()
    )
    return res.data[0] if res.data else None


def update_customer(customer_id: str, payload: dict) -> dict:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("customers")
        .update(payload)
        .eq("id", customer_id)
        .execute()
    )
    return res.data[0] if res.data else {}
