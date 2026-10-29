from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0013_chat_learning'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatinteraction',
            name='answer_characters',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='chatinteraction',
            name='context_characters',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='chatinteraction',
            name='duration_ms',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chatinteraction',
            name='eval_duration_ms',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chatinteraction',
            name='intent',
            field=models.CharField(blank=True, db_index=True, max_length=50),
        ),
        migrations.AddField(
            model_name='chatinteraction',
            name='load_duration_ms',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chatinteraction',
            name='model_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='chatinteraction',
            name='output_tokens',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chatinteraction',
            name='prompt_eval_duration_ms',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chatinteraction',
            name='prompt_tokens',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chatinteraction',
            name='validation_warnings',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
