from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "agentcore_notifier",
            "0006_rename_notifier_no_provider_source_4a7c80_idx_"
            "notifier_no_provide_fcf309_idx_and_more",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="notificationchannel",
            name="name",
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name="notificationchannel",
            name="config",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Webhook: provider_type, url, message_prefix, "
                    "sign_secret, merge_*, silence_window_minutes, "
                    "silence_time_windows; email: smtp_*, from_email, etc."
                ),
            ),
        ),
    ]
