"""Supabase wrapper.

Holds the service-role admin client and a few thin helpers used across the app.
Routes import these instead of touching the supabase client directly, so future
schema or storage changes only have to be made here.
"""

from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY


supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


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
    """Look up a user's role_id in the users table. Returns None if not found."""
    if not user_id:
        return None
    try:
        res = (
            supabase_admin.schema(schema)
            .table("users")
            .select("role_id")
            .eq("id", user_id)
            .execute()
        )
        if res.data:
            return res.data[0].get("role_id")
    except Exception as e:
        print(f"RBAC Query Error: {e}")
    return None
