from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0005_rename_business_user_role'),
    ]

    operations = [
        migrations.CreateModel(
            name='SeuilAlerte',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code_alerte', models.CharField(max_length=64, unique=True)),
                ('type_indicateur', models.CharField(choices=[('ca', "Chiffre d'affaires"), ('volume', 'Volume')], max_length=10)),
                ('seuil_min', models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ('seuil_max', models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ('couleur', models.CharField(choices=[('rouge', 'Rouge'), ('orange', 'Orange'), ('vert', 'Vert')], max_length=10)),
                ('description', models.TextField(blank=True)),
                ('actif', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['type_indicateur', 'code_alerte'],
            },
        ),
        migrations.AddConstraint(
            model_name='seuilalerte',
            constraint=models.CheckConstraint(
                condition=Q(('seuil_min__isnull', True), ('seuil_max__isnull', True), _connector='OR') | Q(('seuil_min__lt', models.F('seuil_max'))),
                name='seuil_alerte_min_inferieur_max',
            ),
        ),
    ]
