from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('sales', '0014_chat_quality_metrics')]

    operations = [
        migrations.AddField(
            model_name='chatinteraction', name='django_duration_ms',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chatinteraction', name='total_duration_ms',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chatinteraction', name='intent_source',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='chatinteraction', name='intent_confidence',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name='vente',
            index=models.Index(fields=['date'], name='vente_date_idx'),
        ),
        migrations.AddIndex(
            model_name='vente',
            index=models.Index(fields=['produit', 'date'], name='vente_produit_date_idx'),
        ),
        migrations.AddIndex(
            model_name='vente',
            index=models.Index(fields=['client', 'date'], name='vente_client_date_idx'),
        ),
        migrations.AddIndex(
            model_name='vente',
            index=models.Index(fields=['region', 'date'], name='vente_region_date_idx'),
        ),
    ]
