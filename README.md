# Agentcore Notifier

[中文](README.zh-CN.md)

Notification management module (webhook, email, etc.) for Django. Part of the agentcore family (with agentcore-metering, agentcore-task).

- Configuration stored in **NotifierConfig** (scope=global, key+value JSON).
- Sending is done only via **Celery task**; no HTTP send API.
- Supports silence and merge rules; see [docs/MERGE_SILENCE_DESIGN.md](docs/MERGE_SILENCE_DESIGN.md).
- Feishu custom bot: [docs/FEISHU_WEBHOOK.md](docs/FEISHU_WEBHOOK.md).

---

## Install

- **Not on PyPI**; install only from GitHub.

**From GitHub** (editable after clone):

```bash
pip install -e git+https://github.com/cloud2ai/agentcore-notifier.git
```

Or, when the host project uses it as a submodule, from repo root:

```bash
pip install -e path/to/agentcore-notifier
```

- Add to `INSTALLED_APPS` in the main project (e.g. DevMind):

```python
'agentcore_notifier.adapters.django',
```

- The host project Dockerfile should iterate over `agentcore/` submodules and run `pip install -e`.
- See the host project README for details.

---

## Configuration

All configuration is stored in the **NotifierConfig** table (scope=global, key+value JSON). No main-project settings or app_config injection; webhook URL, provider, language, etc. are set via notifier UI/API.

Configure via:

- **Django Admin**: NotifierConfig (key=global, silence_rules); NotificationChannel for Webhook/email channels.
- **API**: Channels via `channels/` (CRUD); global and silence via `global/`, `silence-rules/` (see API reference below).

---

## Sending notifications

Send only via **Celery task** (no HTTP send API). The task runs silence and merge checks, then calls WebhookService and writes NotificationRecord.

```python
from agentcore_notifier.adapters.django.tasks.send import send_webhook_notification

send_webhook_notification.delay(
    payload={"msg_type": "post", "content": {...}},
    provider_type="feishu",
    source_app="my_app",
    source_type="alert",
    source_id="123",
    user_id=user_id,
)
```

- See [docs/MERGE_SILENCE_DESIGN.md](docs/MERGE_SILENCE_DESIGN.md) for merge/silence behaviour.
- See [docs/FEISHU_WEBHOOK.md](docs/FEISHU_WEBHOOK.md) for Feishu custom bot message format and optional sign_secret.

---

## API reference

- Mount under an admin prefix (e.g. `api/v1/admin/notifications/`).
- **Auth**: `IsAdminUser` (staff or superuser), otherwise 403.

### Stats and config

| Method | Path | Description |
|--------|------|-------------|
| GET | `.../notification-stats/` | Summary, by_source, by_provider, series |
| GET | `.../notification-records/` | Paginated list of notification records |
| GET / PUT | `.../global/` | Global config (retention_days, cleanup, etc.) |
| GET / PUT | `.../silence-rules/` | Silence rules (NotifierConfig key=silence_rules) |
| GET / POST | `.../channels/` | List and create notification channels (Webhook/Email) |
| GET / PUT / DELETE | `.../channels/<uuid>/` | Get, update, or delete one channel |
| POST | `.../channels/validate/` | Validate channel config without saving |

---

## Cleanup

Cleanup of old notification records is configured via NotifierConfig key=global (`retention_days`, `cleanup_crontab`, `cleanup_enabled`). When enabled, a Celery Beat task runs periodically. Schedule is merged in `AppConfig.ready()`.

---

## Project structure

- `agentcore_notifier/` – Package root.
- `agentcore_notifier/adapters/django/` – Django app: models, admin, views, URLs, Celery tasks.
- `agentcore_notifier/adapters/django/services/` – WebhookService, email, merge/silence, notification_config, stats, cleanup.
- `docs/` – Feishu webhook and other reference docs.
- `tests/` – Pytest tests (Django settings in `tests.settings`).

---

## Tests

From the package root (agentcore-notifier):

```bash
pip install -e ".[dev]"
pytest
```

Run with coverage for the services layer:

```bash
pytest --cov=agentcore_notifier.adapters.django.services --cov-report=term-missing
```

Requires Django and Celery to be configured; `tests.settings` and `tests.conftest` provide the test environment.
