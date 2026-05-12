from datetime import datetime, timezone

from services.supabase_client import supabase_admin

_SCHEMA = "evone_billing"


def list_agents() -> list:
    return (
        supabase_admin.schema(_SCHEMA)
        .table("agents")
        .select("*")
        .order("created_at", desc=False)
        .execute()
        .data or []
    )


def create_agent(payload: dict) -> dict:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("agents")
        .insert(payload)
        .execute()
    )
    return res.data[0] if res.data else {}


def get_agent(agent_id: str) -> dict | None:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("agents")
        .select("*")
        .eq("id", agent_id)
        .execute()
    )
    return res.data[0] if res.data else None


def update_agent(agent_id: str, payload: dict) -> dict:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("agents")
        .update(payload)
        .eq("id", agent_id)
        .execute()
    )
    return res.data[0] if res.data else {}


def delete_agent(agent_id: str) -> dict:
    supabase_admin.schema(_SCHEMA).table("agents").delete().eq("id", agent_id).execute()
    return {"success": True}
