"""Execute the unchanged backend suite under the host's tests/ command."""
from backend.test_backend import (backend, test_sessions_validation_origin_and_reopen,
    test_team_authorization_privacy_and_followup_scope,
    test_bangkok_upsert_windows_eligibility_and_percentage,
    test_registration_rollback_and_composite_foreign_keys,
    test_static_routes_when_frontend_present)
