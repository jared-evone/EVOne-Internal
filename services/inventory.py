from datetime import datetime, timezone

from services.supabase_client import supabase_admin

_SCHEMA = "evone_billing"


def list_products() -> list:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("products")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def create_product(payload: dict) -> dict:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("products")
        .insert(payload)
        .execute()
    )
    return res.data[0] if res.data else {}


def get_product(product_id: str) -> dict | None:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("products")
        .select("*")
        .eq("id", product_id)
        .execute()
    )
    return res.data[0] if res.data else None


def update_product(product_id: str, payload: dict) -> dict:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("products")
        .update(payload)
        .eq("id", product_id)
        .execute()
    )
    return res.data[0] if res.data else {}


def delete_product(product_id: str) -> dict:
    supabase_admin.schema(_SCHEMA).table("products").delete().eq("id", product_id).execute()
    return {"success": True}


def list_movements() -> list:
    res = (
        supabase_admin.schema(_SCHEMA)
        .table("stock_movements")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def create_movement(payload: dict) -> dict:
    product_id = payload["product_id"]
    qty = payload["qty"]
    move_type = payload["type"]

    prod = (
        supabase_admin.schema(_SCHEMA)
        .table("products")
        .select("stock_qty")
        .eq("id", product_id)
        .execute()
    )
    if not prod.data:
        raise ValueError("Product not found")

    current_stock = prod.data[0]["stock_qty"] or 0
    new_stock = current_stock + qty if move_type == "in" else current_stock - qty
    if new_stock < 0:
        raise ValueError(f"Insufficient stock. Current: {current_stock}, requested out: {qty}")

    res = supabase_admin.schema(_SCHEMA).table("stock_movements").insert(payload).execute()

    supabase_admin.schema(_SCHEMA).table("products").update({
        "stock_qty": new_stock,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", product_id).execute()

    return res.data[0] if res.data else {}
