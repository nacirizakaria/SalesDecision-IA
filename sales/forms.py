from django import forms
from django.contrib.auth.models import Group, User

from .models import SeuilAlerte
from .permissions import BUSINESS_USER_GROUP, DECIDEUR_GROUP
from .upload_validation import validate_sales_file

class FichierVenteForm(forms.Form):
    fichier = forms.FileField(
        label="Fichier de ventes (CSV ou Excel)",
        validators=[validate_sales_file],
    )


class OptionalMultipleChoiceField(forms.MultipleChoiceField):
    """Ignore les options vides envoyées par les sélecteurs rapides."""

    def clean(self, value):
        if value:
            value = [item for item in value if item]
        return super().clean(value)


class FiltrePeriodeForm(forms.Form):
    date_debut = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    date_fin = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    clients = OptionalMultipleChoiceField(required=False)
    produits = OptionalMultipleChoiceField(required=False)

    def __init__(self, *args, clients=None, produits=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['clients'].choices = [(client, client) for client in (clients or [])]
        self.fields['produits'].choices = [(produit, produit) for produit in (produits or [])]


class SeuilAlerteForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reference_comparaison'].choices = [
            (SeuilAlerte.ReferenceComparaison.MOIS_PRECEDENT, 'Mois precedent'),
            (SeuilAlerte.ReferenceComparaison.MOYENNE_MOBILE_3, 'Moyenne des 3 mois precedents'),
        ]

    def clean(self):
        cleaned_data = super().clean()
        orange = cleaned_data.get('seuil_orange')
        rouge = cleaned_data.get('seuil_rouge')
        if orange is not None and rouge is not None and rouge >= orange:
            self.add_error('seuil_rouge', 'Le rouge doit etre plus bas que l’orange : par exemple -15 pour rouge et -5 pour orange.')
        return cleaned_data

    class Meta:
        model = SeuilAlerte
        fields = (
            'nom_kpi', 'reference_comparaison', 'seuil_orange', 'seuil_rouge',
            'seuil_minimum_absolu', 'type_comparaison', 'actif', 'description',
        )
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'type_comparaison': forms.HiddenInput(),
        }
        labels = {
            'reference_comparaison': 'Reference',
            'seuil_orange': 'Baisse orange (%)',
            'seuil_rouge': 'Baisse rouge (%)',
            'seuil_minimum_absolu': 'Plancher absolu (DH, optionnel)',
        }


class CreateUserForm(forms.ModelForm):
    """Collecte les attributs; les identifiants sont générés côté serveur."""

    first_name = forms.CharField(label='Prénom', max_length=150, required=True)
    last_name = forms.CharField(label='Nom', max_length=150, required=True)
    email = forms.EmailField(label='Adresse e-mail', required=False)
    group = forms.ModelChoiceField(
        label='Rôle',
        queryset=Group.objects.none(),
        empty_label='Sélectionnez un rôle',
    )

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['group'].queryset = Group.objects.filter(
            name__in=[DECIDEUR_GROUP, BUSINESS_USER_GROUP],
        ).order_by('name')
