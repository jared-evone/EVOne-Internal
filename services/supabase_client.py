"""Supabase wrapper.

Holds the service-role admin client and a few thin helpers used across the app.
Routes import these instead of touching the supabase client directly, so future
schema or storage changes only have to be made here.
"""

import time
from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY


supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# role_id cache: user_id → (role_id, expire_at)
_role_cache: dict[str, tuple[int, float]] = {}
_ROLE_TTL = 300  # seconds


# ---------- Storage ----------

def list_bucket(bucket: str, path: str = "") -> list:
    """Return non-hidden entries from a storage bucket path."""
    res = supabase_admin.storage.from_(bucket).list(path=path)
    return [f for f in res if f.get("name") and not f.get("name").startswith(".")]


def signed_url(bucket: str, path: str, expires_in: int = 3600) -> str | None:
    res = supabase_admin.storage.from_(bucket).create_signed_url(path, expires_in)
    return res.get("signedURL")


def upload_to_bucket(bucket: str, path: str, file_bytes: bytes, content_type: str) -> None:
    supabase_admin.storage.from_(bucket).upload(
        path=path,
        file=file_bytes,
        file_options={"content-type": content_type, "x-upsert": "true"},
    )


# ---------- RBAC ----------

def get_user_role_id(user_id: str, schema: str = "evone_billing") -> int | None:
    """Look up a user's role_id. Result is cached in memory for 5 minutes."""
    if not user_id:
        return None
    now = time.monotonic()
    hit = _role_cache.get(user_id)
    if hit and now < hit[1]:
        return hit[0]
    try:
        res = (
            supabase_admin.schema(schema)
            .table("users")
            .select("role_id")
            .eq("id", user_id)
            .execute()
        )
        if res.data:
            role_id = res.data[0].get("role_id")
            _role_cache[user_id] = (role_id, now + _ROLE_TTL)
            return role_id
    except Exception as e:
        print(f"RBAC Query Error: {e}")
    return None


def invalidate_role_cache(user_id: str) -> None:
    _role_cache.pop(user_id, None)
