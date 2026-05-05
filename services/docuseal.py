"""DocuSeal REST wrapper.

All DocuSeal HTTP calls go through this module. Adding a new operation means
adding one function here, not scattering `requests.post(...)` across routes.
"""

import requests

from config import DOCUSEAL_API_KEY, DOCUSEAL_BASE_URL, template_id


_TIMEOUT = 30


def _headers(json: bool = False) -> dict:
    h = {"X-Auth-Token": DOCUSEAL_API_KEY}
    if json:
        h["Content-Type"] = "application/json"
    return h


def _request(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{DOCUSEAL_BASE_URL}{path}"
    kwargs.setdefault("timeout", _TIMEOUT)
    return requests.request(method, url, **kwargs)


# ---------- Submissions ----------

def resolve_template_and_submitters(form_type: str, signers_count: str, data: dict) -> tuple[str | None, list]:
    """Map (form_type, signers_count) to (template_id, submitters list).

    Returns (None, []) if the form type / signer count combo isn't supported.
    Mirrors the original logic from app.py.
    """
    tid = None
    submitters: list = []

    if form_type == "Form A":
        if signers_count == "1":
            tid = template_id("FORM_A_1P")
            submitters = [
                {"role": "ES", "email": data.get("email_es"), "name": data.get("name_es")},
            ]
        else:
            tid = template_id("FORM_A_2P")
            submitters = [
                {"role": "ES", "email": data.get("email_es"), "name": data.get("name_es")},
                {"role": "LEW", "email": data.get("email_lew"), "name": data.get("name_lew")},
            ]
    elif form_type in ("Form D", "Form 1"):
        suffix = "FORM_D" if form_type == "Form D" else "FORM_1"
        if signers_count == "3":
            tid = template_id(f"{suffix}_3P")
            submitters = [
                {"role": "Inspector", "email": data.get("email_inspector"), "name": data.get("name_inspector")},
                {"role": "ES", "email": data.get("email_es"), "name": data.get("name_es")},
                {"role": "LEW", "email": data.get("email_lew"), "name": data.get("name_lew")},
            ]
        else:
            tid = template_id(f"{suffix}_2P")
            submitters = [
                {"role": "ES", "email": data.get("email_es"), "name": data.get("name_es")},
                {"role": "LEW", "email": data.get("email_lew"), "name": data.get("name_lew")},
            ]

    return tid, submitters


def create_submission(template_id_int: int, document_name: str, submitters: list) -> dict:
    payload = {
        "template_id": template_id_int,
        "name": document_name,
        "send_email": True,
        "message": {
            "subject": document_name,
            "body": "Hello {{submitter.name}},\n\nPlease complete the document via the link: {{submitter.link}}",
        },
        "submitters": submitters,
    }
    res = _request("POST", "/submissions", json=payload, headers=_headers(json=True))
    return res.json()


def list_submissions() -> list | dict:
    res = _request("GET", "/submissions", headers=_headers())
    return res.json() if res.ok else []


def get_submission(sub_id: str) -> tuple[bool, dict]:
    """Return (ok, data). Caller decides what to do on failure."""
    res = _request("GET", f"/submissions/{sub_id}", headers=_headers())
    if not res.ok:
        return False, {}
    return True, res.json()


def fetch_url_bytes(url: str) -> bytes | None:
    """Download an arbitrary URL (used for the signed-PDF URL DocuSeal returns)."""
    res = requests.get(url, timeout=_TIMEOUT)
    return res.content if res.ok else None


def resend_submitter(submitter_id: int) -> tuple[bool, dict]:
    """PUT against a submitter with send_email=true to retrigger the email."""
    res = _request(
        "PUT",
        f"/submitters/{submitter_id}",
        json={"send_email": True},
        headers=_headers(json=True),
    )
    if res.ok:
        return True, {}
    try:
        body = res.json()
    except ValueError:
        body = {}
    return False, body
