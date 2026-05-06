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

"""Sales pipeline + customer CRM data access.

Wraps Supabase queries against the evone_billing schema:
- customers: corporate accounts
- contacts: people at those accounts
- deals: sales pipeline (stages: new, quoted, negotiating, won, lost)

Run migrations/001_sales_crm.sql against your Supabase project before using.
"""

from datetime import datetime, timezone

from services.supabase_client import supabase_admin


_SCHEMA = "evone_billing"

ALLOWED_STAGES = {"new", "quoted", "negotiating", "won", "lost"}
TERMINAL_STAGES = {"won", "lost"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table(name: str):
    return supabase_admin.schema(_SCHEMA).table(name)


# ----------------------------------------------------------------------
# Customers
# ----------------------------------------------------------------------

def list_customers(status: str | None = None) -> list[dict]:
    q = _table("customers").select("*").order("name")
    if status:
        q = q.eq("status", status)
    return q.execute().data or []


def create_customer(data: dict) -> dict:
    if not data.get("name"):
        return {"error": True, "message": "name is required"}
    payload = {
        "name": data["name"],
        "status": data.get("status", "prospect"),
        "account_manager_id": data.get("account_manager_id"),
        "notes": data.get("notes"),
    }
    res = _table("customers").insert(payload).execute()
    return res.data[0] if res.data else {}


def get_customer(customer_id: str) -> dict:
    """Customer record with embedded contacts list."""
    res = _table("customers").select("*").eq("id", customer_id).execute()
    if not res.data:
        return {}
    cust = res.data[0]
    cust["contacts"] = list_contacts(customer_id)
    return cust


def update_customer(customer_id: str, data: dict) -> dict:
    allowed = {"name", "status", "account_manager_id", "notes"}
    payload = {k: v for k, v in data.items() if k in allowed}
    if not payload:
        return {"error": True, "message": "no updatable fields supplied"}
    payload["updated_at"] = _now()
    res = _table("customers").update(payload).eq("id", customer_id).execute()
    return res.data[0] if res.data else {}


def delete_customer(customer_id: str) -> dict:
    _table("customers").delete().eq("id", customer_id).execute()
    return {"success": True}


# ----------------------------------------------------------------------
# Contacts
# ----------------------------------------------------------------------

def list_contacts(customer_id: str) -> list[dict]:
    return (
        _table("contacts")
        .select("*")
        .eq("customer_id", customer_id)
        .order("name")
        .execute()
        .data
        or []
    )


def create_contact(customer_id: str, data: dict) -> dict:
    if not data.get("name"):
        return {"error": True, "message": "name is required"}
    payload = {
        "customer_id": customer_id,
        "name": data["name"],
        "email": data.get("email"),
        "phone": data.get("phone"),
        "role": data.get("role"),
        "notes": data.get("notes"),
    }
    res = _table("contacts").insert(payload).execute()
    return res.data[0] if res.data else {}


def update_contact(contact_id: str, data: dict) -> dict:
    allowed = {"name", "email", "phone", "role", "notes"}
    payload = {k: v for k, v in data.items() if k in allowed}
    if not payload:
        return {"error": True, "message": "no updatable fields supplied"}
    res = _table("contacts").update(payload).eq("id", contact_id).execute()
    return res.data[0] if res.data else {}


def delete_contact(contact_id: str) -> dict:
    _table("contacts").delete().eq("id", contact_id).execute()
    return {"success": True}


# ----------------------------------------------------------------------
# Deals
# ----------------------------------------------------------------------

def list_deals(stage: str | None = None, customer_id: str | None = None) -> list[dict]:
    q = _table("deals").select("*").order("created_at", desc=True)
    if stage:
        q = q.eq("stage", stage)
    if customer_id:
        q = q.eq("customer_id", customer_id)
    return q.execute().data or []


def create_deal(data: dict) -> dict:
    if not data.get("title"):
        return {"error": True, "message": "title is required"}
    stage = (data.get("stage") or "new").lower()
    if stage not in ALLOWED_STAGES:
        return {"error": True, "message": f"invalid stage. allowed: {sorted(ALLOWED_STAGES)}"}
    payload = {
        "customer_id": data.get("customer_id"),
        "title": data["title"],
        "stage": stage,
        "amount": data.get("amount"),
        "currency": data.get("currency", "SGD"),
        "owner_id": data.get("owner_id"),
        "expected_close_date": data.get("expected_close_date"),
        "notes": data.get("notes"),
    }
    if stage in TERMINAL_STAGES:
        payload["closed_at"] = _now()
    res = _table("deals").insert(payload).execute()
    return res.data[0] if res.data else {}


def get_deal(deal_id: str) -> dict:
    res = _table("deals").select("*").eq("id", deal_id).execute()
    return res.data[0] if res.data else {}


def update_deal(deal_id: str, data: dict) -> dict:
    allowed = {
        "customer_id", "title", "stage", "amount", "currency",
        "owner_id", "expected_close_date", "notes",
    }
    payload = {k: v for k, v in data.items() if k in allowed}
    if not payload:
        return {"error": True, "message": "no updatable fields supplied"}
    if "stage" in payload:
        stage = (payload["stage"] or "").lower()
        if stage not in ALLOWED_STAGES:
            return {"error": True, "message": f"invalid stage. allowed: {sorted(ALLOWED_STAGES)}"}
        payload["stage"] = stage
        # Stamp closed_at when entering won/lost; clear it when moving back.
        payload["closed_at"] = _now() if stage in TERMINAL_STAGES else None
    payload["updated_at"] = _now()
    res = _table("deals").update(payload).eq("id", deal_id).execute()
    return res.data[0] if res.data else {}


def delete_deal(deal_id: str) -> dict:
    _table("deals").delete().eq("id", deal_id).execute()
    return {"success": True}


# ----------------------------------------------------------------------
# Pipeline summary (handy for dashboards later)
# ----------------------------------------------------------------------

def pipeline_summary() -> dict:
    """Counts and total amount per stage. Cheap aggregate for dashboards."""
    deals = list_deals()
    summary: dict[str, dict] = {s: {"count": 0, "amount": 0.0} for s in ALLOWED_STAGES}
    for d in deals:
        s = d.get("stage")
        if s in summary:
            summary[s]["count"] += 1
            summary[s]["amount"] += float(d.get("amount") or 0)
    return summary
