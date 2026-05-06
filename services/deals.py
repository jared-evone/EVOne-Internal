from datetime import datetime, timezone

from services.supabase_client import supabase_admin

_SCHEMA = "evone_billing"


def list_deals() -> list:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("deals")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def create_deal(payload: dict) -> dict:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("deals")
        .insert(payload)
        .execute()
    )
    return res.data[0] if res.data else {}


def get_deal(deal_id: str) -> dict | None:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("deals")
        .select("*")
        .eq("id", deal_id)
        .execute()
    )
    return res.data[0] if res.data else None


def update_deal(deal_id: str, payload: dict) -> dict:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("deals")
        .update(payload)
        .eq("id", deal_id)
        .execute()
    )
    return res.data[0] if res.data else {}
