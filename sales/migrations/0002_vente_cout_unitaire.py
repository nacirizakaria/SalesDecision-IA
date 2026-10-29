        # Generated for DecisionIQ KPI completion

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='vente',
            name='cout_unitaire',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]
