"""Centralized environment configuration.

Every env var the app reads is declared here, in one place. Importing this
module loads the .env file (if present) and exposes the values as constants.
A clear startup error is raised if a required variable is missing, so we fail
fast at boot rather than mid-request.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in your .env file (see .env.example) or in the Render dashboard."
        )
    return value


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# Supabase
SUPABASE_URL = _require("SUPABASE_URL")
SUPABASE_ANON_KEY = _require("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = _require("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_JWT_SECRET = _require("SUPABASE_JWT_SECRET")

# DocuSeal
DOCUSEAL_API_KEY = _require("DOCUSEAL_API_KEY")
DOCUSEAL_BASE_URL = _optional("DOCUSEAL_BASE_URL", "https://api.docuseal.com")

# DocuSeal template IDs — read lazily via os.environ at call time so missing
# template IDs only fail the specific form-type they apply to, not app startup.
def template_id(suffix: str) -> str | None:
    """Return the DocuSeal template ID for a form variant, or None if unset.

    Examples: template_id("FORM_A_1P"), template_id("FORM_D_3P").
    """
    return os.environ.get(f"TEMPLATE_ID_{suffix}")
