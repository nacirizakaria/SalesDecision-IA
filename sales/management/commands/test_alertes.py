from django.core.management.base import BaseCommand

from sales.models import SeuilAlerte
from sales.services.alertes import evaluer_alertes


class Command(BaseCommand):
    help = "Crée des seuils de démonstration et affiche l'évaluation d'alertes CA."

    def handle(self, *args, **options):
        seuils = [
            {
                'code_alerte': 'baisse_ca',
                'type_indicateur': 'ca',
                'seuil_min': '-10.00',
                'seuil_max': None,
                'couleur': 'rouge',
                'description': 'Baisse de CA supérieure à 10 %.',
            },
            {
                'code_alerte': 'hausse_anormale',
                'type_indicateur': 'ca',
                'seuil_min': None,
                'seuil_max': '20.00',
                'couleur': 'orange',
                'description': 'Hausse de CA supérieure à 20 % à vérifier.',
            },
        ]
        for valeurs in seuils:
            code_alerte = valeurs.pop('code_alerte')
            SeuilAlerte.objects.update_or_create(code_alerte=code_alerte, defaults=valeurs)

        for evolution in (-15, 30, 2):
            self.stdout.write(str(evaluer_alertes(evolution, 'ca')))
