from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

class Vente(models.Model):
    date = models.DateField(blank=True, null=True)
    client = models.CharField(max_length=255, blank=True, null=True)
    produit = models.CharField(max_length=255, blank=True, null=True)
    quantite = models.IntegerField(default=0)
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cout_unitaire = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    region = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        permissions = [
            (
                'import_sales',
                'Peut importer des fichiers de ventes',
            ),
            (
                'configure_thresholds',
                'Peut configurer les seuils d’alerte',
            ),
        ]
        indexes = [
            models.Index(fields=['date'], name='vente_date_idx'),
            models.Index(fields=['produit', 'date'], name='vente_produit_date_idx'),
            models.Index(fields=['client', 'date'], name='vente_client_date_idx'),
            models.Index(fields=['region', 'date'], name='vente_region_date_idx'),
        ]

    def ca(self):
        return self.quantite * self.prix_unitaire

    def cout_total(self):
        return self.quantite * self.cout_unitaire

    def marge(self):
        return self.ca() - self.cout_total()

    def __str__(self):
        return f"{self.produit or 'Produit non renseigne'} - {self.date or 'Date non renseignee'}"


class SeuilAlerte(models.Model):
    """Seuil paramétrable utilisé pour qualifier une évolution de CA ou de volume."""

    class TypeIndicateur(models.TextChoices):
        CA = 'ca', "Chiffre d'affaires"
        VOLUME = 'volume', 'Volume'

    class Couleur(models.TextChoices):
        ROUGE = 'rouge', 'Rouge'
        ORANGE = 'orange', 'Orange'
        VERT = 'vert', 'Vert'

    class TypeComparaison(models.TextChoices):
        INFERIEUR = 'inferieur', 'Valeur inférieure au seuil'
        SUPERIEUR = 'superieur', 'Valeur supérieure au seuil'
        BAISSE_PCT = 'baisse_pct', 'Pourcentage de baisse'
        ECART_PCT = 'ecart_pct', 'Écart en pourcentage'

    class ReferenceComparaison(models.TextChoices):
        MOIS_PRECEDENT = 'mois_precedent', 'Mois precedent'
        MOYENNE_MOBILE_3 = 'moyenne_mobile_3', 'Moyenne des 3 mois precedents'
        PREVISION_IA = 'prevision_ia', 'Prevision IA validee'

    code_alerte = models.CharField(max_length=64, unique=True)
    type_indicateur = models.CharField(max_length=10, choices=TypeIndicateur.choices)
    seuil_min = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    seuil_max = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    couleur = models.CharField(max_length=10, choices=Couleur.choices)
    description = models.TextField(blank=True)
    actif = models.BooleanField(default=True)
    nom_kpi = models.CharField(max_length=100, blank=True)
    seuil_vert = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    seuil_orange = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    seuil_rouge = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    type_comparaison = models.CharField(
        max_length=20,
        choices=TypeComparaison.choices,
        default=TypeComparaison.INFERIEUR,
    )
    reference_comparaison = models.CharField(
        max_length=24,
        choices=ReferenceComparaison.choices,
        default=ReferenceComparaison.MOYENNE_MOBILE_3,
    )
    seuil_minimum_absolu = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Filet de securite optionnel, propre a l'entreprise.",
    )
    modifie_par = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='seuils_alertes_modifies',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(seuil_min__isnull=True) | Q(seuil_max__isnull=True) | Q(seuil_min__lt=models.F('seuil_max')),
                name='seuil_alerte_min_inferieur_max',
            ),
        ]
        ordering = ['type_indicateur', 'code_alerte']

    def clean(self):
        super().clean()
        if self.seuil_min is not None and self.seuil_max is not None and self.seuil_min >= self.seuil_max:
            raise ValidationError({'seuil_max': 'Le seuil maximum doit être strictement supérieur au seuil minimum.'})

    def __str__(self):
        return f"{self.code_alerte} ({self.type_indicateur})"


class HistoriqueConfigurationAlerte(models.Model):
    """Trace les modifications de seuils effectuees par les decideurs."""

    seuil = models.ForeignKey(SeuilAlerte, on_delete=models.CASCADE, related_name='historique_configurations')
    modifie_par = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL)
    seuil_orange = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    seuil_rouge = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    reference_comparaison = models.CharField(max_length=24)
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.seuil.code_alerte} - {self.created_at:%Y-%m-%d %H:%M}"


class UserProvisioning(models.Model):
    """Etat de securite lie a la creation administrative d'un compte."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='provisioning',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='provisioned_users',
    )
    must_change_password = models.BooleanField(default=True)
    temporary_password_expires_at = models.DateTimeField()
    password_changed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Provisioning de {self.user.get_username()}"


class UserProvisioningAudit(models.Model):
    """Journal sans secret des operations de provisioning."""

    class Action(models.TextChoices):
        CREATED = 'created', 'Utilisateur cree'
        PASSWORD_CHANGED = 'password_changed', 'Mot de passe remplace'

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name='provisioning_actions',
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='provisioning_audit_events',
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class LoginThrottle(models.Model):
    """Compteur persistant de tentatives, indexé par une empreinte compte+IP."""

    key_hash = models.CharField(max_length=64, unique=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    window_started_at = models.DateTimeField(auto_now_add=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class ChatInteraction(models.Model):
    """Question/réponse journalisée pour recueillir un feedback explicite."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='sales_chat_interactions',
    )
    question = models.CharField(max_length=500)
    answer = models.TextField()
    provider = models.CharField(max_length=32)
    model_name = models.CharField(max_length=100, blank=True)
    intent = models.CharField(max_length=50, blank=True, db_index=True)
    provider_response_id = models.CharField(max_length=255, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    django_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    total_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    intent_source = models.CharField(max_length=32, blank=True)
    intent_confidence = models.FloatField(null=True, blank=True)
    load_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    prompt_eval_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    eval_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    context_characters = models.PositiveIntegerField(default=0)
    answer_characters = models.PositiveIntegerField(default=0)
    validation_warnings = models.JSONField(default=list, blank=True)
    helpful = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class LearnedChatExample(models.Model):
    """Exemple validé servant à mieux comprendre les formulations futures."""

    interaction = models.OneToOneField(
        ChatInteraction, on_delete=models.CASCADE, related_name='learned_example',
    )
    normalized_question = models.CharField(max_length=500, db_index=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
