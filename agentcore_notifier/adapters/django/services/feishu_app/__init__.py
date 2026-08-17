"""
Feishu self-built app: tenant_access_token, DM sending, and the shared
event/card-callback verification used by both endpoints.

Distinct from services/webhook/feishu.py (custom-bot incoming webhook,
group-only, no callback). This can DM a specific person by open_id and
receive interactive card actions back — that's the whole reason it exists.
"""
