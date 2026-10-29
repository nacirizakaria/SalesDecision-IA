from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('sales', '0006_seuilalerte'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name='seuilalerte', name='modifie_par', field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name='seuils_alertes_modifies', to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name='seuilalerte', name='nom_kpi', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='seuilalerte', name='seuil_orange', field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name='seuilalerte', name='seuil_rouge', field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name='seuilalerte', name='seuil_vert', field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name='seuilalerte', name='type_comparaison', field=models.CharField(choices=[('inferieur', 'Valeur inférieure au seuil'), ('superieur', 'Valeur supérieure au seuil'), ('baisse_pct', 'Pourcentage de baisse'), ('ecart_pct', 'Écart en pourcentage')], default='inferieur', max_length=20)),
    ]
