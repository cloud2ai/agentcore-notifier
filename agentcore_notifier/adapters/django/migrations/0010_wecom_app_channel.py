"""Add the wecom_app channel type alongside wecom_bot.

Purely additive. wecom_bot is deprecated (its message permission expires
after 7 days and needs a human to re-authorize) but stays a valid choice
and keeps working, because channels already configured against it would
otherwise stop delivering the moment this migration ran -- the two carry
different credentials (botid/secret/userid vs corp_id/corp_secret/
agent_id) so there is nothing to convert them into automatically.

Steering users off it belongs in the UI, where the recommendation can be
shown next to the choice, not in a migration that silently disables what
they set up.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agentcore_notifier", "0009_alter_notificationchannel_channel_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notificationchannel",
            name="channel_type",
            field=models.CharField(
                choices=[
                    ("webhook", "Webhook"),
                    ("email", "Email"),
                    ("sms", "SMS"),
                    ("feishu_app", "Feishu App"),
                    ("wecom_bot", "WeCom Bot (deprecated, 7-day auth)"),
                    ("wecom_app", "WeCom App"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
