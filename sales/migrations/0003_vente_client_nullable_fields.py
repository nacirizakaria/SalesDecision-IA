from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0002_vente_cout_unitaire'),
    ]

    operations = [
        migrations.AddField(
            model_name='vente',
            name='client',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='vente',
            name='date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='vente',
            name='produit',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='vente',
            name='quantite',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='vente',
            name='prix_unitaire',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]
