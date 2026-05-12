from datetime import datetime, timezone

from services.supabase_client import supabase_admin

_SCHEMA = "evone_billing"


def list_deals(owner_id: str | None = None) -> list:
    q = (
        supabase_admin.schema(_SCHEMA)
        .table("deals")
        .select("*")
        .order("created_at", desc=True)
    )
    if owner_id:
        q = q.eq("owner_id", owner_id)
    return q.execute().data or []


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


def delete_deal(deal_id: str) -> dict:
    supabase_admin.schema(_SCHEMA).table("deals").delete().eq("id", deal_id).execute()
    return {"success": True}


def list_deal_items(deal_id: str) -> list:
    return (
        supabase_admin.schema(_SCHEMA)
        .table("deal_items")
        .select("*")
        .eq("deal_id", deal_id)
        .order("created_at")
        .execute()
        .data or []
    )


def set_deal_items(deal_id: str, items: list) -> list:
    supabase_admin.schema(_SCHEMA).table("deal_items").delete().eq("deal_id", deal_id).execute()
    if not items:
        return []
    for item in items:
        item["deal_id"] = deal_id
    res = supabase_admin.schema(_SCHEMA).table("deal_items").insert(items).execute()
    return res.data or []
