# EVOne-Internal

Internal web app for the EVOne team — document management, e-signing, and corporate-charging billing reports. Backend is FastAPI; frontend is Jinja2-rendered HTML with vanilla JS. Hosted on Render.

## Stack

- **Backend**: Python 3.12, FastAPI, Uvicorn
- **Auth**: Supabase JWT (HS256), with role-based access control via `evone_billing.users.role_id` (1 = Admin, 2 = Finance, 3 = Read-Only)
- **Storage / DB**: Supabase (service-role client, buckets `Documents` and `Form`)
- **E-sign**: DocuSeal REST API
- **Reports**: ReportLab (PDF) + pandas + xlsxwriter (Excel)

## Layout

```
app.py                    # FastAPI app: middleware, auth, routes
config.py                 # All env var reads in one place
services/
  supabase_client.py      # Storage + RBAC helpers
  docuseal.py             # DocuSeal REST wrapper
templates/                # Jinja2 pages (billing, signing, files, analytics)
static/                   # Login page, logo
render.yaml               # Render service config
.env.example              # Template for local env vars
.github/workflows/ci.yml  # Compile-check on PRs
```

## Local development

1. Install Python 3.12 and create a virtualenv.
2. Install deps: `pip install -r requirements.txt`
3. Copy env template: `cp .env.example .env`, then fill in real values from the Render dashboard or your team lead.
4. Run: `uvicorn app:app --reload --port 8000`
5. Open http://localhost:8000 — sign in with a Supabase user.

## Environment variables

See [.env.example](.env.example) for the full list. All are required for the app to boot (it fails fast in `config.py`). Production values live in the Render dashboard; `render.yaml` only declares which keys are required.

## How to add a new endpoint

Add a route in [app.py](app.py):

```python
@app.post("/api/your-endpoint")
def your_endpoint(payload: dict, user: dict = Depends(get_current_user)):
    if not check_is_admin(user):
        raise HTTPException(status_code=403, detail="Admins only")
    # ... business logic ...
    return {"ok": True}
```

- `Depends(get_current_user)` enforces a valid Supabase JWT.
- `check_is_admin(user)` enforces the `role_id == 1` rule. Drop it for read-only endpoints.

## How to add a new third-party API

The `services/` layer keeps integrations isolated. Adding e.g. Stripe:

1. Add `STRIPE_API_KEY` (and any other vars) to:
   - `config.py` (`STRIPE_API_KEY = _require("STRIPE_API_KEY")`)
   - `.env.example`
   - `render.yaml` (with `sync: false`)
2. Create `services/stripe_client.py` — typed functions wrapping the API. Follow the pattern in [services/docuseal.py](services/docuseal.py): a single `_request` helper that sets headers, applies a timeout, and the public functions on top.
3. Set the production value in the Render dashboard.
4. Import the new module in [app.py](app.py) and call its functions from your routes.
5. Update this README's stack section.

When [app.py](app.py) crosses ~800 lines or you have 3+ feature areas, split routes into a `routers/` package using FastAPI's `APIRouter`.

## Deploying

- `main` branch auto-deploys to Render (configured in [render.yaml](render.yaml)).
- Build: `pip install -r requirements.txt`. Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`.
- Secrets are managed in the Render dashboard, not in git.

## CI

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs `python -m py_compile` on the source files for every PR and push to `main`. Catches import/syntax breaks before they hit Render.
