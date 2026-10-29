import base64
import json
import logging
import os
import re
import time
import unicodedata
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.forms import modelformset_factory
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Min, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncYear
from django.db import connection
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST
from django.core.cache import cache
from django.contrib.staticfiles import finders
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils import timezone

from .forms import CreateUserForm, FichierVenteForm, FiltrePeriodeForm, SeuilAlerteForm
from .models import ChatInteraction, HistoriqueConfigurationAlerte, SeuilAlerte, UserProvisioningAudit, Vente
from .permissions import administrator_required, configure_thresholds_required, import_sales_required
from .prediction import predire_ca_pour_ventes
from .recommandations import generer_recommandations
from .services.alertes import SEUILS_PAR_DEFAUT, construire_alertes_dashboard, etats_alertes_dashboard, initialiser_seuils_par_defaut
from .services.user_provisioning import provision_user
from .services.openai_sales_assistant import (
    AssistantConfigurationError,
    ask_sales_assistant,
    build_sales_context,
    detect_question_intent,
)
from .services.chat_learning import find_validated_examples, record_feedback
from .services.assistant_analytics import execute_intent
from .services.assistant_intents import IntentName, resolve_intent
from .services.assistant_memory import clear_memory, get_memory, update_memory
from .upload_validation import SalesUploadError, read_sales_file


weasyprint_dll_directory_handle = None
logger = logging.getLogger(__name__)


def health_check(request):
    """Sonde minimale pour le reverse proxy et la supervision."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        logger.exception('Echec de la sonde de base de donnees')
        return JsonResponse({'status': 'unavailable'}, status=503)
    return JsonResponse({'status': 'ok'})


COLONNES_ALIASES = {
    'date': 'date',
    'client': 'client',
    'clients': 'client',
    'nom client': 'client',
    'nom_client': 'client',
    'customer': 'client',
    'produit': 'produit',
    'produits': 'produit',
    'product': 'produit',
    'quantite': 'quantite',
    'quantité': 'quantite',
    'qte': 'quantite',
    'volume': 'quantite',
    'prix': 'prix_unitaire',
    'prix_unitaire': 'prix_unitaire',
    'prix unitaire': 'prix_unitaire',
    'prix vente': 'prix_unitaire',
    'prix_vente': 'prix_unitaire',
    'cout': 'cout_unitaire',
    'coût': 'cout_unitaire',
    'cout_unitaire': 'cout_unitaire',
    'coût_unitaire': 'cout_unitaire',
    'cout unitaire': 'cout_unitaire',
    'coût unitaire': 'cout_unitaire',
    'prix_achat': 'cout_unitaire',
    'prix achat': 'cout_unitaire',
    'region': 'region',
    'région': 'region',
}

COLONNES_ATTENDUES = ['date', 'client', 'produit', 'quantite', 'prix_unitaire', 'cout_unitaire', 'region']
COLONNES_NUMERIQUES = ['quantite', 'prix_unitaire', 'cout_unitaire']
COLONNES_CALCULEES = ['ca', 'marge', 'objectif']
COLONNES_TEXTE = ['client', 'produit', 'region']


def normaliser_nom_colonne(nom):
    nom = str(nom).strip().lower().replace('\ufeff', '')
    nom = unicodedata.normalize('NFKD', nom)
    nom = ''.join(caractere for caractere in nom if not unicodedata.combining(caractere))
    nom = re.sub(r'[^a-z0-9]+', ' ', nom)
    return re.sub(r'\s+', ' ', nom).strip()


ALIASES_BRUTS = {
    'date': [
        'date', 'jour', 'date vente', 'date de vente', 'date commande', 'date de commande',
        'date transaction', 'date de transaction', 'transaction date', 'sale date', 'sales date',
        'order date', 'invoice date', 'billing date', 'periode', 'period',
    ],
    'client': [
        'client', 'clients', 'nom client', 'nom du client', 'nom_client', 'client nom',
        'customer', 'customer name', 'buyer', 'acheteur', 'compte client', 'societe',
        'société', 'entreprise', 'company', 'account', 'account name', 'raison sociale',
    ],
    'produit': [
        'produit', 'produits', 'nom produit', 'nom du produit', 'produit nom', 'product',
        'product name', 'article', 'articles', 'item', 'item name', 'designation',
        'désignation', 'libelle', 'libellé', 'sku', 'reference', 'référence', 'ref',
        'categorie produit', 'catégorie produit',
    ],
    'quantite': [
        'quantite', 'quantité', 'qte', 'qté', 'qty', 'quantity', 'volume', 'volumes',
        'nombre', 'nb', 'nb ventes', 'nombre ventes', 'nombre de ventes', 'unites',
        'unités', 'units', 'units sold', 'quantite vendue', 'quantité vendue',
        'volume vendu', 'sales volume',
    ],
    'prix_unitaire': [
        'prix', 'prix unitaire', 'prix_unitaire', 'pu', 'prix unit', 'prix unite',
        'prix unité', 'prix de vente', 'prix vente', 'prix_vente',
        'prix de vente unitaire', 'prix unitaire vente', 'tarif', 'tarif unitaire',
        'unit price', 'selling price', 'sale price', 'sales price', 'price',
        'price unit', 'unit selling price', 'revenue per unit',
    ],
    'cout_unitaire': [
        'cout', 'coût', 'cout unitaire', 'coût unitaire', 'cout_unitaire',
        'coût_unitaire', 'cout unite', 'coût unité', 'cu', 'prix achat',
        'prix_achat', 'prix d achat', 'prix dachat', 'cout achat', 'coût achat',
        'cout de revient', 'coût de revient', 'cost', 'unit cost', 'purchase price',
        'buying price', 'cost price', 'unit purchase price',
    ],
    'region': [
        'region', 'région', 'zone', 'zone geographique', 'zone géographique',
        'secteur', 'secteur commercial', 'ville', 'city', 'localite', 'localité',
        'province', 'territoire', 'territory', 'area', 'location', 'localisation',
        'pays', 'country',
    ],
}

COLONNES_ALIASES = {
    normaliser_nom_colonne(alias): champ
    for champ, aliases in ALIASES_BRUTS.items()
    for alias in aliases
}

ALIASES_COMPLEMENTAIRES = {
    'date': [
        'mois', 'annee', 'date facture', 'date livraison',
    ],
    'client': [
        'cl', 'code client', 'id client', 'customer id', 'client id', 'tiers',
    ],
    'produit': [
        'code produit', 'product code', 'famille produit', 'product category',
    ],
    'quantite': [
        'qte vendue', 'quantites', 'quantités', 'quantité vendue', 'quantite vendue',
    ],
    'prix_unitaire': [
        'prix moyen', 'prix moyen vente', 'unit selling price', 'prix unit',
    ],
    'cout_unitaire': [
        'cout moyen', 'coût moyen', 'unit purchase cost', 'purchase unit cost',
    ],
    'region': [
        'agence', 'branche', 'filiale', 'delegation', 'délégation', 'wilaya',
    ],
    'ca': [
        'ca', 'c a', 'chiffre affaires', 'chiffre d affaires', 'chiffre daffaires',
        'chiffre d affaire', 'chiffre affaire', 'montant', 'montant vente',
        'montant ventes', 'montant ht', 'total', 'total vente', 'total ventes',
        'revenu', 'revenus', 'revenue', 'sales', 'sales amount', 'turnover',
        'amount', 'net sales',
    ],
    'marge': [
        'marge', 'marge totale', 'marge brute', 'profit', 'benefice', 'bénéfice',
        'gain', 'gross margin', 'margin',
    ],
    'objectif': [
        'objectif', 'objectifs', 'target', 'goal', 'quota', 'budget', 'prevision',
        'prévision', 'forecast', 'objectif ca',
    ],
    'numero': [
        'n', 'no', 'n°', 'num', 'numero', 'numéro', 'id', 'identifiant',
        'ref facture', 'numero facture', 'numéro facture', 'invoice no', 'invoice number',
    ],
}

COLONNES_ALIASES.update({
    normaliser_nom_colonne(alias): champ
    for champ, aliases in ALIASES_COMPLEMENTAIRES.items()
    for alias in aliases
})


def normaliser_colonnes(df):
    colonnes = {}
    noms_utilises = set()
    for colonne in df.columns:
        nom = normaliser_nom_colonne(colonne)
        nom = COLONNES_ALIASES.get(nom, nom.replace(' ', '_'))
        if nom not in noms_utilises:
            colonnes[colonne] = nom
            noms_utilises.add(nom)
    return df.rename(columns=colonnes)


def completer_colonnes_manquantes(df):
    manquantes = []
    for colonne in COLONNES_ATTENDUES:
        if colonne not in df.columns:
            manquantes.append(colonne)
            df[colonne] = 0 if colonne in COLONNES_NUMERIQUES else None
    return df, manquantes


def completer_depuis_colonnes_calculees(df):
    if 'ca' in df.columns:
        masque_prix_manquant = (df['prix_unitaire'] == 0) & (df['quantite'] > 0)
        df.loc[masque_prix_manquant, 'prix_unitaire'] = df.loc[masque_prix_manquant, 'ca'] / df.loc[masque_prix_manquant, 'quantite']

    if 'marge' in df.columns:
        ca_ligne = df['ca'] if 'ca' in df.columns else df['quantite'] * df['prix_unitaire']
        masque_cout_manquant = (df['cout_unitaire'] == 0) & (df['quantite'] > 0)
        df.loc[masque_cout_manquant, 'cout_unitaire'] = (
            (ca_ligne.loc[masque_cout_manquant] - df.loc[masque_cout_manquant, 'marge'])
            / df.loc[masque_cout_manquant, 'quantite']
        )

    df.loc[df['prix_unitaire'] < 0, 'prix_unitaire'] = 0
    df.loc[df['cout_unitaire'] < 0, 'cout_unitaire'] = 0
    return df


def expression_ca():
    return ExpressionWrapper(
        F('quantite') * F('prix_unitaire'),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def expression_cout():
    return ExpressionWrapper(
        F('quantite') * F('cout_unitaire'),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def expression_marge():
    return ExpressionWrapper(
        expression_ca() - expression_cout(),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def importer_dataframe(df):
    if df.empty:
        return [], [], "Le fichier est vide. Ajoutez au moins une ligne de vente."

    df = normaliser_colonnes(df)
    df, colonnes_manquantes = completer_colonnes_manquantes(df)

    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    for colonne in COLONNES_NUMERIQUES + COLONNES_CALCULEES:
        if colonne not in df.columns:
            continue
        df[colonne] = pd.to_numeric(df[colonne], errors='coerce').fillna(0)
        df.loc[df[colonne] < 0, colonne] = 0

    df = completer_depuis_colonnes_calculees(df)

    for colonne in COLONNES_TEXTE:
        df[colonne] = df[colonne].where(pd.notna(df[colonne]), None)
        df[colonne] = df[colonne].apply(lambda valeur: str(valeur).strip() if valeur is not None else None)
        df[colonne] = df[colonne].apply(lambda valeur: valeur if valeur else None)

    ventes = []
    for _, row in df.iterrows():
        ventes.append(Vente(
            date=row['date'].date() if pd.notna(row['date']) else None,
            client=row['client'],
            produit=row['produit'],
            quantite=int(row['quantite']),
            prix_unitaire=row['prix_unitaire'],
            cout_unitaire=row['cout_unitaire'],
            region=row['region'],
        ))

    Vente.objects.bulk_create(ventes)
    return ventes, colonnes_manquantes, None


@import_sales_required
def import_ventes(request):
    message = None
    erreur = None

    if request.method == 'POST':
        form = FichierVenteForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                df = read_sales_file(form.cleaned_data['fichier'])
            except SalesUploadError as exc:
                erreur = str(exc)
                return render(request, 'sales/import_ventes.html', {'form': form, 'erreur': erreur})

            ventes, colonnes_manquantes, erreur = importer_dataframe(df)
            if erreur:
                return render(request, 'sales/import_ventes.html', {'form': form, 'erreur': erreur})

            message = f"{len(ventes)} vente(s) importee(s) avec succes."
            if colonnes_manquantes:
                message += (
                    " Colonnes absentes completees automatiquement : "
                    f"{', '.join(colonnes_manquantes)}."
                )
    else:
        form = FichierVenteForm()

    return render(request, 'sales/import_ventes.html', {'form': form, 'message': message, 'erreur': erreur})


def appliquer_filtres(ventes, date_debut=None, date_fin=None, clients=None, produits=None):
    if date_debut:
        ventes = ventes.filter(date__gte=date_debut)
    if date_fin:
        ventes = ventes.filter(date__lte=date_fin)
    if clients:
        ventes = ventes.filter(client__in=clients)
    if produits:
        ventes = ventes.filter(produit__in=produits)
    return ventes


def filtrer_ventes(date_debut=None, date_fin=None, clients=None, produits=None):
    return appliquer_filtres(Vente.objects.all(), date_debut, date_fin, clients, produits)


@login_required
def liste_ventes(request):
    ventes = Vente.objects.all().order_by('-date', '-id')
    query = request.GET.get('q', '').strip()
    if query:
        ventes = ventes.filter(
            Q(client__icontains=query)
            | Q(produit__icontains=query)
            | Q(region__icontains=query)
        )
    return render(request, 'sales/liste_ventes.html', {'ventes': ventes, 'search_query': query})


def grouper_ca(ventes, champ_date, alias):
    return list(
        ventes
        .exclude(date__isnull=True)
        .annotate(**{alias: champ_date})
        .values(alias)
        .annotate(ca=Sum(expression_ca()), marge=Sum(expression_marge()), volume=Sum('quantite'), nombre_ventes=Count('id'))
        .order_by(alias)
    )


def calculer_kpis(date_debut=None, date_fin=None, clients=None, produits=None):
    ventes = filtrer_ventes(date_debut, date_fin, clients, produits)
    ca_expr = expression_ca()
    marge_expr = expression_marge()

    agregats = ventes.aggregate(
        ca_total=Sum(ca_expr),
        marge_totale=Sum(marge_expr),
        quantite_totale=Sum('quantite'),
    )

    nombre_ventes = ventes.count()
    ca_total = agregats['ca_total'] or 0
    marge_totale = agregats['marge_totale'] or 0
    quantite_totale = agregats['quantite_totale'] or 0
    panier_moyen = ca_total / nombre_ventes if nombre_ventes else 0

    ca_par_jour = grouper_ca(ventes, TruncDay('date'), 'jour')
    ca_par_mois = grouper_ca(ventes, TruncMonth('date'), 'mois')
    ca_par_annee = grouper_ca(ventes, TruncYear('date'), 'annee')
    for periode in [*ca_par_jour, *ca_par_mois, *ca_par_annee]:
        periode['panier'] = (periode['ca'] / periode['nombre_ventes']) if periode['nombre_ventes'] else 0

    evolution_ca = None
    evolution_marge = None
    if len(ca_par_mois) >= 2:
        dernier = ca_par_mois[-1]['ca']
        precedent = ca_par_mois[-2]['ca']
        if precedent:
            evolution_ca = round(((dernier - precedent) / precedent) * 100, 2)

        derniere_marge = ca_par_mois[-1]['marge']
        marge_precedente = ca_par_mois[-2]['marge']
        if marge_precedente:
            evolution_marge = round(((derniere_marge - marge_precedente) / marge_precedente) * 100, 2)

    evolution_volume = None
    if len(ca_par_mois) >= 2:
        dernier_volume = ca_par_mois[-1]['volume']
        precedent_volume = ca_par_mois[-2]['volume']
        if precedent_volume:
            evolution_volume = round(((dernier_volume - precedent_volume) / precedent_volume) * 100, 2)

    produit_top = (
        ventes
        .exclude(produit__isnull=True)
        .exclude(produit='')
        .values('produit')
        .annotate(ca=Sum(ca_expr), quantite=Sum('quantite'))
        .order_by('-ca')
        .first()
    )

    client_top = (
        ventes
        .exclude(client__isnull=True)
        .exclude(client='')
        .values('client')
        .annotate(ca=Sum(ca_expr), quantite=Sum('quantite'))
        .order_by('-ca')
        .first()
    )

    region_top = (
        ventes
        .exclude(region__isnull=True)
        .exclude(region='')
        .values('region')
        .annotate(ca=Sum(ca_expr))
        .order_by('-ca')
        .first()
    )

    return {
        'ca_total': ca_total,
        'marge_totale': marge_totale,
        'nombre_ventes': nombre_ventes,
        'quantite_totale': quantite_totale,
        'panier_moyen': panier_moyen,
        'produit_top': produit_top,
        'client_top': client_top,
        'region_top': region_top,
        'ca_par_jour': ca_par_jour,
        'ca_par_mois': ca_par_mois,
        'ca_par_annee': ca_par_annee,
        'evolution': evolution_ca,
        'evolution_marge': evolution_marge,
        'evolution_volume': evolution_volume,
    }


def repartition_par_produit(date_debut=None, date_fin=None, clients=None, produits=None):
    ventes = filtrer_ventes(date_debut, date_fin, clients, produits)
    return list(
        ventes
        .exclude(produit__isnull=True)
        .exclude(produit='')
        .values('produit')
        .annotate(ca=Sum(expression_ca()), volume=Sum('quantite'))
        .order_by('-ca')
    )


def repartition_par_client(date_debut=None, date_fin=None, clients=None, produits=None):
    ventes = filtrer_ventes(date_debut, date_fin, clients, produits)
    return list(
        ventes
        .exclude(client__isnull=True)
        .exclude(client='')
        .values('client')
        .annotate(ca=Sum(expression_ca()), volume=Sum('quantite'))
        .order_by('-ca')
    )


def repartition_par_region(date_debut=None, date_fin=None, clients=None, produits=None):
    ventes = filtrer_ventes(date_debut, date_fin, clients, produits)
    return list(
        ventes
        .exclude(region__isnull=True)
        .exclude(region='')
        .values('region')
        .annotate(ca=Sum(expression_ca()), volume=Sum('quantite'))
        .order_by('-ca')
    )


def json_decimal_liste(valeurs):
    return json.dumps([float(v) for v in valeurs])


def serie_temporelle(groupes, cle_date, format_label):
    return {
        'labels': [g[cle_date].strftime(format_label) for g in groupes],
        'ca': [float(g['ca'] or 0) for g in groupes],
        'marge': [float(g['marge'] or 0) for g in groupes],
        'volume': [g['volume'] or 0 for g in groupes],
    }


def construire_contexte_pdf(request, granularite, dimension):
    """Construit uniquement les donnees necessaires a un export PDF."""
    ventes_source = Vente.objects.all()
    clients = list(ventes_source.exclude(client__isnull=True).exclude(client='').values_list('client', flat=True).distinct().order_by('client'))
    produits = list(ventes_source.exclude(produit__isnull=True).exclude(produit='').values_list('produit', flat=True).distinct().order_by('produit'))
    filtre_form = FiltrePeriodeForm(request.GET or None, clients=clients, produits=produits)
    date_debut = date_fin = None
    clients_selectionnes = produits_selectionnes = []
    if filtre_form.is_valid():
        date_debut = filtre_form.cleaned_data.get('date_debut')
        date_fin = filtre_form.cleaned_data.get('date_fin')
        clients_selectionnes = filtre_form.cleaned_data.get('clients') or []
        produits_selectionnes = filtre_form.cleaned_data.get('produits') or []

    ventes = appliquer_filtres(ventes_source, date_debut, date_fin, clients_selectionnes, produits_selectionnes)
    ca_expr, marge_expr = expression_ca(), expression_marge()
    agregats = ventes.aggregate(ca_total=Sum(ca_expr), marge_totale=Sum(marge_expr), quantite_totale=Sum('quantite'), nombre_ventes=Count('id'))
    ca_total = agregats['ca_total'] or 0
    nombre_ventes = agregats['nombre_ventes'] or 0

    mensuel = grouper_ca(ventes, TruncMonth('date'), 'mois')
    evolution_ca = evolution_volume = None
    if len(mensuel) >= 2:
        dernier, precedent = mensuel[-1], mensuel[-2]
        if precedent['ca']:
            evolution_ca = round(((dernier['ca'] - precedent['ca']) / precedent['ca']) * 100, 2)
        if precedent['volume']:
            evolution_volume = round(((dernier['volume'] - precedent['volume']) / precedent['volume']) * 100, 2)

    configurations = {
        'jour': (TruncDay('date'), 'jour', '%d/%m/%Y', 31),
        'mois': (TruncMonth('date'), 'mois', '%m/%Y', 24),
        'annee': (TruncYear('date'), 'annee', '%Y', 10),
    }
    fonction_date, cle_date, format_label, limite_points = configurations[granularite]
    groupes_performance = mensuel[-limite_points:] if granularite == 'mois' else grouper_ca(ventes, fonction_date, cle_date)[-limite_points:]
    performance = serie_temporelle(groupes_performance, cle_date, format_label)

    def repartition(champ):
        return list(ventes.exclude(**{f'{champ}__isnull': True}).exclude(**{champ: ''}).values(champ).annotate(ca=Sum(ca_expr), volume=Sum('quantite')).order_by('-ca'))

    repartitions = {'produit': repartition('produit'), 'region': repartition('region')}
    if dimension == 'client':
        repartitions['client'] = repartition('client')
    repartition_selectionnee = repartitions[dimension]
    champ_dimension = {'produit': 'produit', 'client': 'client', 'region': 'region'}[dimension]
    top_repartition = repartition_selectionnee[:5]
    autres = repartition_selectionnee[5:]
    if autres:
        top_repartition.append({
            champ_dimension: 'Autres',
            'ca': sum((ligne['ca'] or 0) for ligne in autres),
            'volume': sum((ligne['volume'] or 0) for ligne in autres),
        })

    def premier(champ):
        return repartitions[champ][0] if repartitions[champ] else None

    return {
        'kpis': {
            'ca_total': ca_total,
            'marge_totale': agregats['marge_totale'] or 0,
            'quantite_totale': agregats['quantite_totale'] or 0,
            'nombre_ventes': nombre_ventes,
            'panier_moyen': ca_total / nombre_ventes if nombre_ventes else 0,
            'evolution': evolution_ca,
            'evolution_volume': evolution_volume,
            'produit_top': premier('produit'),
            'region_top': premier('region'),
        },
        'performance_pdf': performance,
        'repartition_pdf': top_repartition,
        'date_debut': date_debut,
        'date_fin': date_fin,
        'filtres_actifs': {'date_debut': date_debut, 'date_fin': date_fin, 'clients': clients_selectionnes, 'produits': produits_selectionnes},
    }


def construire_contexte_dashboard(request):
    ventes = Vente.objects.all()
    clients = list(
        ventes
        .exclude(client__isnull=True)
        .exclude(client='')
        .values_list('client', flat=True)
        .distinct()
        .order_by('client')
    )
    produits = list(
        ventes
        .exclude(produit__isnull=True)
        .exclude(produit='')
        .values_list('produit', flat=True)
        .distinct()
        .order_by('produit')
    )

    filtre_form = FiltrePeriodeForm(request.GET or None, clients=clients, produits=produits)
    date_debut = None
    date_fin = None
    clients_selectionnes = []
    produits_selectionnes = []
    if filtre_form.is_valid():
        date_debut = filtre_form.cleaned_data.get('date_debut')
        date_fin = filtre_form.cleaned_data.get('date_fin')
        clients_selectionnes = filtre_form.cleaned_data.get('clients') or []
        produits_selectionnes = filtre_form.cleaned_data.get('produits') or []

    kpis = calculer_kpis(date_debut, date_fin, clients_selectionnes, produits_selectionnes)
    try:
        horizon_prevision = int(request.GET.get('horizon', 3))
    except (TypeError, ValueError):
        horizon_prevision = 3
    horizon_prevision = horizon_prevision if horizon_prevision in {3, 6, 12} else 3
    ventes_filtrees = filtrer_ventes(date_debut, date_fin, clients_selectionnes, produits_selectionnes)
    prediction_ca = predire_ca_pour_ventes(
        ventes_filtrees,
        nb_mois=horizon_prevision,
        force_refresh=request.GET.get('refresh_prevision') == '1',
    )
    dernier_ca_reel = kpis['ca_par_mois'][-1]['ca'] if kpis['ca_par_mois'] else None
    prochain_ca_prevu = prediction_ca['valeurs'][0] if prediction_ca['valeurs'] else None
    variation_prevue = None
    if dernier_ca_reel:
        variation_prevue = round(((prochain_ca_prevu - float(dernier_ca_reel)) / float(dernier_ca_reel)) * 100, 2) if prochain_ca_prevu is not None else None
    tendance_prevision = 'stable'
    if variation_prevue is not None:
        tendance_prevision = 'hausse' if variation_prevue > 3 else 'baisse' if variation_prevue < -3 else 'stable'
    lignes_prevision = []
    for index, mois in enumerate(prediction_ca['mois']):
        intervalle = (prediction_ca.get('intervalle_confiance') or [])[index] if index < len(prediction_ca.get('intervalle_confiance') or []) else None
        lignes_prevision.append({
            'mois': mois,
            'valeur': prediction_ca['valeurs'][index],
            'basse': intervalle['basse'] if intervalle else None,
            'haute': intervalle['haute'] if intervalle else None,
        })
    repartition_produit = repartition_par_produit(date_debut, date_fin, clients_selectionnes, produits_selectionnes)
    repartition_client = repartition_par_client(date_debut, date_fin, clients_selectionnes, produits_selectionnes)
    repartition_region = repartition_par_region(date_debut, date_fin, clients_selectionnes, produits_selectionnes)
    alertes_dashboard = construire_alertes_dashboard(kpis, prediction_ca)
    comparaison_recommandations = request.GET.get('comparaison_recommandations', 'previous_month')
    if comparaison_recommandations not in {'previous_month', 'same_month_previous_year', 'previous_year'}:
        comparaison_recommandations = 'previous_month'
    recommandations_moteur = generer_recommandations(
        ventes_filtrees,
        prediction_ca,
        comparison_mode=comparaison_recommandations,
    )
    provenance = ventes_filtrees.aggregate(
        nombre_lignes=Count('id'),
        premiere_vente=Min('date'),
        derniere_vente=Max('date'),
    )
    provenance.update({
        'filtres_clients': clients_selectionnes,
        'filtres_produits': produits_selectionnes,
        'date_debut': date_debut,
        'date_fin': date_fin,
    })
    explication_prevision = (
        "ARIMA analyse la dynamique mensuelle observée et sélectionne automatiquement "
        "la combinaison ayant le meilleur critère AIC."
        if prediction_ca['methode'] == 'arima'
        else "La moyenne mobile pondérée privilégie les trois mois les plus récents "
        "(poids 50 %, 30 % et 20 %)."
    )
    series_temporelles = {
        'jour': serie_temporelle(kpis['ca_par_jour'], 'jour', '%d/%m/%Y'),
        'mois': serie_temporelle(kpis['ca_par_mois'], 'mois', '%m/%Y'),
        'annee': serie_temporelle(kpis['ca_par_annee'], 'annee', '%Y'),
    }
    if date_debut and date_fin:
        periode_analyse = f"{date_debut:%d/%m/%Y} — {date_fin:%d/%m/%Y}"
    elif date_debut:
        periode_analyse = f"Depuis le {date_debut:%d/%m/%Y}"
    elif date_fin:
        periode_analyse = f"Jusqu’au {date_fin:%d/%m/%Y}"
    else:
        periode_analyse = "Toutes les données"

    return {
        'kpis': kpis,
        'filtre_form': filtre_form,
        'clients': clients,
        'produits': produits,
        'clients_selectionnes': clients_selectionnes,
        'produits_selectionnes': produits_selectionnes,
        'date_debut': date_debut,
        'date_fin': date_fin,
        'series_temporelles': json.dumps(series_temporelles),
        'prediction_ca': json.dumps(prediction_ca),
        'periode_analyse': periode_analyse,
        'prediction_ca_details': prediction_ca,
        'horizon_prevision': horizon_prevision,
        'prochain_ca_prevu': prochain_ca_prevu,
        'variation_prevue': variation_prevue,
        'tendance_prevision': tendance_prevision,
        'lignes_prevision': lignes_prevision,
        'alertes_dashboard': alertes_dashboard,
        'provenance_prevision': provenance,
        'explication_prevision': explication_prevision,
        'recommandations': recommandations_moteur,
        'comparaison_recommandations': comparaison_recommandations,
        'assistant_openai_configured': (
            settings.LLM_PROVIDER == 'ollama' or bool(os.getenv('OPENAI_API_KEY'))
        ),
        'client_labels': json.dumps([r['client'] for r in repartition_client]),
        'client_ca_data': json_decimal_liste([r['ca'] for r in repartition_client]),
        'client_volume_data': json.dumps([r['volume'] or 0 for r in repartition_client]),
        'produit_labels': json.dumps([r['produit'] for r in repartition_produit]),
        'produit_ca_data': json_decimal_liste([r['ca'] for r in repartition_produit]),
        'produit_volume_data': json.dumps([r['volume'] or 0 for r in repartition_produit]),
        'region_labels': json.dumps([r['region'] for r in repartition_region]),
        'region_ca_data': json_decimal_liste([r['ca'] for r in repartition_region]),
        'region_volume_data': json.dumps([r['volume'] or 0 for r in repartition_region]),
        'repartition_produit': repartition_produit,
        'repartition_client': repartition_client,
        'repartition_region': repartition_region,
        'ventes_recentes': list(
            filtrer_ventes(date_debut, date_fin, clients_selectionnes, produits_selectionnes)
            .order_by('-date', '-id')[:6]
        ),
    }


@login_required
def dashboard(request):
    return render(request, 'sales/dashboard.html', construire_contexte_dashboard(request))


@login_required
@require_POST
def recommendation_chat(request):
    total_started_at = time.perf_counter()
    """Assistant GPT global, ancré dans les agrégats du périmètre autorisé."""
    rate_key = f"recommendation-chat:{request.user.pk}"
    request_count = cache.get(rate_key, 0)
    if request_count >= 30:
        return JsonResponse(
            {'error': 'Trop de questions. Réessayez dans une minute.'},
            status=429,
        )
    cache.set(rate_key, request_count + 1, timeout=60)
    try:
        payload = json.loads(request.body)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Requête JSON invalide.'}, status=400)
    question = str(payload.get('question') or '').strip()
    if not question or len(question) > 500:
        return JsonResponse(
            {'error': 'La question doit contenir entre 1 et 500 caractères.'},
            status=400,
        )
    history = payload.get('history') or []
    if not isinstance(history, list) or len(history) > 20:
        return JsonResponse({'error': 'Historique de conversation invalide.'}, status=400)
    context = construire_contexte_dashboard(request)
    scoped_sales = filtrer_ventes(
        context['date_debut'], context['date_fin'],
        context['clients_selectionnes'], context['produits_selectionnes'],
    )
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key
    memory = get_memory(request.user.pk, session_key)
    catalog = {
        'products': list(
            scoped_sales.exclude(produit__isnull=True)
            .values_list('produit', flat=True).distinct()[:200]
        ),
        'clients': list(
            scoped_sales.exclude(client__isnull=True)
            .values_list('client', flat=True).distinct()[:200]
        ),
        'regions': list(
            scoped_sales.exclude(region__isnull=True)
            .values_list('region', flat=True).distinct()[:100]
        ),
    }
    plan, intent_source = resolve_intent(
        question, catalog, memory,
        use_llm=settings.ASSISTANT_USE_LLM_INTENT and settings.LLM_PROVIDER == 'ollama',
    )
    if plan.needs_clarification or plan.intent == IntentName.CLARIFICATION:
        return JsonResponse({
            'answer': plan.clarification_question,
            'clarification': True,
            'grounded': True,
            'quality': {
                'intent': plan.intent.value,
                'intent_source': intent_source,
                'confidence': plan.confidence,
            },
        })
    if plan.intent == IntentName.UNSUPPORTED:
        return JsonResponse({
            'answer': (
                'Je peux uniquement analyser les données commerciales autorisées. '
                'Reformulez votre demande autour d’un KPI, produit, client, région ou prévision.'
            ),
            'grounded': True,
            'quality': {'intent': plan.intent.value, 'intent_source': intent_source},
        })

    # Une période explicitement formulée par l'utilisateur est prioritaire sur
    # les dates du dashboard. Les filtres client/produit restent toutefois actifs.
    assistant_sales = scoped_sales
    if plan.filters.start_date or plan.filters.end_date:
        assistant_sales = filtrer_ventes(
            clients=context['clients_selectionnes'],
            produits=context['produits_selectionnes'],
        )
    analytical_context = build_sales_context(
        assistant_sales,
        question,
        context['recommandations'],
    )
    intent = plan.intent.value
    normalized_question = normaliser_nom_colonne(question)
    if any(term in normalized_question for term in ('prevision', 'forecast', 'ca_prevu', 'caprevu')):
        analytical_context['forecast'] = {
            'type_source': 'prevision',
            'scope': 'global',
            'method': context['prediction_ca_details'].get('methode'),
            'reliability': context['prediction_ca_details'].get('fiabilite'),
            'history_depth': context['prediction_ca_details'].get('profondeur_historique'),
            'last_actual_period': (
                context['kpis']['ca_par_mois'][-1]['mois'].strftime('%m/%Y')
                if context['kpis']['ca_par_mois'] else None
            ),
            'last_actual_ca': (
                float(context['kpis']['ca_par_mois'][-1]['ca'])
                if context['kpis']['ca_par_mois'] else None
            ),
            'variation_pct': context['variation_prevue'],
            'rows': context['lignes_prevision'],
            'warnings': context['prediction_ca_details'].get('avertissements') or [],
        }
    forecast_context = analytical_context.get('forecast') or {
        'method': context['prediction_ca_details'].get('methode'),
        'reliability': context['prediction_ca_details'].get('fiabilite'),
        'rows': context['lignes_prevision'],
        'warnings': context['prediction_ca_details'].get('avertissements') or [],
    }
    business_result = execute_intent(plan, assistant_sales, forecast_context)
    analytical_context['validated_intent'] = plan.model_dump(mode='json')
    analytical_context['business_result'] = business_result
    analytical_context['conversation_memory'] = memory
    if intent == 'product_analysis':
        analytical_context['products'] = [
            {
                'entity': row['produit'], 'scope': 'product',
                'type_source': 'realise', 'ca': float(row['ca'] or 0),
                'volume': float(row['volume'] or 0),
            }
            for row in context['repartition_produit'][:10]
        ]
    if intent == 'region_analysis':
        analytical_context['regions'] = [
            {
                'entity': row['region'], 'scope': 'region',
                'type_source': 'realise', 'ca': float(row['ca'] or 0),
                'volume': float(row['volume'] or 0),
            }
            for row in context['repartition_region'][:10]
        ]
    analytical_context['validated_examples'] = find_validated_examples(question, request.user)
    django_duration_ms = round((time.perf_counter() - total_started_at) * 1000)
    try:
        answer, response_id, provider, metrics = ask_sales_assistant(
            question=question,
            context=analytical_context,
            history=history,
            user_identifier=f"user:{request.user.pk}",
        )
    except AssistantConfigurationError as exc:
        return JsonResponse(
            {'error': str(exc), 'configuration_required': True},
            status=503,
        )
    except Exception:
        logger.exception("Echec de l'assistant commercial LLM")
        return JsonResponse(
            {'error': "L’assistant local est momentanément indisponible. Réessayez dans quelques instants."},
            status=502,
        )
    model_name = (
        settings.OLLAMA_ASSISTANT_MODEL if provider == 'ollama'
        else provider
    )
    interaction = ChatInteraction.objects.create(
        user=request.user,
        question=question,
        answer=answer,
        provider=provider,
        model_name=model_name,
        intent=intent,
        provider_response_id=response_id,
        duration_ms=metrics.get('duration_ms'),
        django_duration_ms=django_duration_ms,
        total_duration_ms=round((time.perf_counter() - total_started_at) * 1000),
        intent_source=intent_source,
        intent_confidence=plan.confidence,
        load_duration_ms=metrics.get('load_duration_ms'),
        prompt_eval_duration_ms=metrics.get('prompt_eval_duration_ms'),
        eval_duration_ms=metrics.get('eval_duration_ms'),
        prompt_tokens=metrics.get('prompt_tokens'),
        output_tokens=metrics.get('output_tokens'),
        context_characters=len(json.dumps(analytical_context, ensure_ascii=False, default=str)),
        answer_characters=len(answer),
        validation_warnings=metrics.get('validation_warnings') or [],
    )
    logger.info(
        "assistant_complete user=%s intent=%s source=%s django_ms=%s ollama_ms=%s total_ms=%s",
        request.user.pk, intent, intent_source, django_duration_ms,
        metrics.get('duration_ms'), interaction.total_duration_ms,
    )
    update_memory(request.user.pk, session_key, plan, business_result)
    return JsonResponse({
        'answer': answer,
        'response_id': response_id,
        'interaction_id': interaction.pk,
        'model': model_name,
        'provider': provider,
        'grounded': True,
        'quality': {
            'intent': intent,
            'intent_source': intent_source,
            'intent_confidence': plan.confidence,
            'duration_ms': metrics.get('duration_ms'),
            'validation_warnings': metrics.get('validation_warnings') or [],
        },
    })


@login_required
@require_POST
def recommendation_chat_clear(request):
    session_key = request.session.session_key
    if session_key:
        clear_memory(request.user.pk, session_key)
    return JsonResponse({'message': 'Conversation effacée.'})


@login_required
@require_POST
def recommendation_chat_stream(request):
    """Flux NDJSON : statut immédiat, puis réponse finale en segments sûrs."""
    def event_stream():
        yield json.dumps({
            'type': 'status', 'message': 'Analyse des données en cours…',
        }, ensure_ascii=False) + '\n'
        response = recommendation_chat(request)
        try:
            data = json.loads(response.content)
        except (TypeError, ValueError):
            data = {'error': 'Réponse de l’assistant invalide.'}
        if response.status_code >= 400:
            yield json.dumps({
                'type': 'error', 'message': data.get('error'),
                'status': response.status_code,
            }, ensure_ascii=False) + '\n'
            return
        answer = str(data.pop('answer', ''))
        words = answer.split()
        for index in range(0, len(words), 12):
            yield json.dumps({
                'type': 'delta',
                'content': ' '.join(words[index:index + 12]) + (
                    ' ' if index + 12 < len(words) else ''
                ),
            }, ensure_ascii=False) + '\n'
        yield json.dumps({'type': 'done', **data}, ensure_ascii=False) + '\n'

    response = StreamingHttpResponse(
        event_stream(), content_type='application/x-ndjson; charset=utf-8',
    )
    response['Cache-Control'] = 'no-cache, no-store'
    response['X-Accel-Buffering'] = 'no'
    return response


@login_required
@require_POST
def recommendation_chat_feedback(request):
    try:
        payload = json.loads(request.body)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Requête JSON invalide.'}, status=400)
    interaction_id = payload.get('interaction_id')
    helpful = payload.get('helpful')
    if not isinstance(helpful, bool):
        return JsonResponse({'error': 'Le feedback doit être positif ou négatif.'}, status=400)
    interaction = ChatInteraction.objects.filter(
        pk=interaction_id, user=request.user,
    ).first()
    if interaction is None:
        return JsonResponse({'error': 'Interaction introuvable.'}, status=404)
    record_feedback(interaction, helpful)
    return JsonResponse({
        'saved': True,
        'learned': helpful,
        'message': (
            'Merci, cette formulation aidera les prochaines réponses.'
            if helpful else 'Merci, cette réponse ne sera pas utilisée comme exemple.'
        ),
    })


@configure_thresholds_required
def configurer_alertes(request):
    initialiser_seuils_par_defaut()
    codes = [code for code, *_ in SEUILS_PAR_DEFAUT]
    FormSet = modelformset_factory(SeuilAlerte, form=SeuilAlerteForm, extra=0)
    queryset = SeuilAlerte.objects.filter(code_alerte__in=codes).order_by('code_alerte')
    if request.method == 'POST':
        formset = FormSet(request.POST, queryset=queryset)
        if formset.is_valid():
            configurations = formset.save(commit=False)
            for configuration in configurations:
                configuration.modifie_par = request.user
                configuration.save()
                HistoriqueConfigurationAlerte.objects.create(
                    seuil=configuration,
                    modifie_par=request.user,
                    seuil_orange=configuration.seuil_orange,
                    seuil_rouge=configuration.seuil_rouge,
                    reference_comparaison=configuration.reference_comparaison,
                    actif=configuration.actif,
                )
            messages.success(request, 'Les seuils d’alerte ont été enregistrés.')
            return redirect('configurer_alertes')
    else:
        formset = FormSet(queryset=queryset)
    etats_alertes = etats_alertes_dashboard(calculer_kpis())
    for form in formset.forms:
        form.etat_alerte = etats_alertes.get(form.instance.code_alerte, {})
    return render(request, 'sales/configurer_alertes.html', {
        'formset': formset,
        'etats_alertes': etats_alertes,
        'historique_configurations': HistoriqueConfigurationAlerte.objects.select_related('seuil', 'modifie_par')[:8],
    })


@administrator_required
def create_user(request):
    credentials = None
    if request.method == 'POST':
        form = CreateUserForm(request.POST)
        if form.is_valid():
            credentials = provision_user(
                creator=request.user,
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name'],
                email=form.cleaned_data['email'],
                group=form.cleaned_data['group'],
            )
            form = CreateUserForm()
    else:
        form = CreateUserForm()

    response = render(request, 'sales/create_user.html', {
        'form': form,
        'credentials': credentials,
    })
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    response['Pragma'] = 'no-cache'
    return response


@administrator_required
def security_users(request):
    """Vue d'administration des accès, sans exposer aucun secret en clair."""

    users = list(
        get_user_model().objects
        .select_related('provisioning', 'provisioning__created_by')
        .prefetch_related('groups')
        .order_by('-date_joined')
    )
    now = timezone.now()
    rows = []
    for user in users:
        provisioning = getattr(user, 'provisioning', None)
        if provisioning and provisioning.must_change_password:
            password_status = (
                'expired' if provisioning.temporary_password_expires_at <= now else 'temporary'
            )
        elif provisioning:
            password_status = 'changed'
        else:
            password_status = 'standard'
        rows.append({
            'user': user,
            'role': user.groups.first().name if user.groups.exists() else (
                'Administrateur' if user.is_staff else 'Sans rôle'
            ),
            'provisioning': provisioning,
            'password_status': password_status,
        })

    audits = UserProvisioningAudit.objects.select_related('actor', 'target_user')[:10]
    return render(request, 'sales/security_users.html', {
        'security_rows': rows,
        'recent_audits': audits,
        'active_count': sum(1 for user in users if user.is_active),
        'temporary_count': sum(1 for row in rows if row['password_status'] == 'temporary'),
        'expired_count': sum(1 for row in rows if row['password_status'] == 'expired'),
    })


@require_POST
@administrator_required
def delete_user_account(request, user_id):
    User = get_user_model()
    target = User.objects.filter(pk=user_id).first()
    if target is None:
        messages.error(request, 'Ce compte utilisateur est introuvable.')
    elif target.pk == request.user.pk:
        messages.error(request, 'Vous ne pouvez pas supprimer votre propre compte.')
    elif target.is_staff or target.is_superuser:
        messages.error(request, 'Un compte administrateur ne peut pas être supprimé depuis cette page.')
    elif target.provisioned_users.exists():
        messages.error(request, 'Ce compte a créé d’autres utilisateurs et doit être conservé pour la traçabilité.')
    else:
        display_name = target.get_full_name() or target.get_username()
        target.delete()
        messages.success(request, f'Le compte de {display_name} a été supprimé.')
    return redirect('security_users')


def graphique_svg(labels, series, titre):
    """Construit un graphique SVG autonome, compatible avec WeasyPrint."""
    largeur, hauteur = 620, 220
    marge_gauche, marge_droite, marge_haut, marge_bas = 42, 18, 28, 42
    largeur_trace = largeur - marge_gauche - marge_droite
    hauteur_trace = hauteur - marge_haut - marge_bas
    valeurs_montant = [
        float(valeur or 0)
        for nom, donnees, _ in series if nom != 'Volume vendu'
        for valeur in donnees
    ]
    valeurs_volume = [
        float(valeur or 0)
        for nom, donnees, _ in series if nom == 'Volume vendu'
        for valeur in donnees
    ]
    maximum_montant = max(valeurs_montant, default=0) or 1
    maximum_volume = max(valeurs_volume, default=0) or 1
    nombre_points = max(len(labels), 1)
    pas = largeur_trace / nombre_points
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largeur} {hauteur}" role="img" aria-label="{escape(titre)}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]

    for index in range(5):
        y = marge_haut + hauteur_trace * index / 4
        valeur_montant = maximum_montant * (4 - index) / 4
        valeur_volume = maximum_volume * (4 - index) / 4
        elements.append(f'<line x1="{marge_gauche}" y1="{y:.1f}" x2="{largeur - marge_droite}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        elements.append(f'<text x="{marge_gauche - 5}" y="{y + 3:.1f}" text-anchor="end" font-size="8" fill="#64748b">{valeur_montant:.0f}</text>')
        elements.append(f'<text x="{largeur - marge_droite + 5}" y="{y + 3:.1f}" font-size="8" fill="#2563eb">{valeur_volume:.0f}</text>')

    elements.extend([
        f'<text x="2" y="{marge_haut - 8}" font-size="8" fill="#64748b">(DH)</text>',
        f'<text x="{largeur - 58}" y="{marge_haut - 8}" font-size="8" fill="#2563eb"></text>',
    ])

    pas_libelles = max(1, (len(labels) + 7) // 8)
    for index, label in enumerate(labels):
        if index % pas_libelles and index != len(labels) - 1:
            continue
        x = marge_gauche + pas * (index + 0.5)
        elements.append(f'<text x="{x:.1f}" y="{hauteur - 17}" text-anchor="middle" font-size="8" fill="#475569">{escape(str(label))}</text>')

    for serie_index, (nom, donnees, couleur) in enumerate(series):
        maximum = maximum_volume if nom == 'Volume vendu' else maximum_montant
        points = []
        for index, valeur in enumerate(donnees):
            x = marge_gauche + pas * (index + 0.5)
            y = marge_haut + hauteur_trace * (1 - float(valeur or 0) / maximum)
            points.append(f'{x:.1f},{y:.1f}')
        if points:
            elements.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{couleur}" stroke-width="2.5"/>')
        elements.append(f'<text x="{marge_gauche + 165 + 105 * serie_index}" y="15" font-size="9" fill="{couleur}">&#9679; {escape(nom)}</text>')

    elements.append('</svg>')
    return mark_safe(''.join(elements))


def graphique_performance_svg(serie, granularite='mois'):
    """Graphique combine lisible : CA, marge et volume sur leurs echelles adaptees."""
    libelle = {'jour': 'Jour', 'mois': 'Mois', 'annee': 'Annee'}[granularite]
    labels, ca, marge, volume = serie['labels'], serie['ca'], serie['marge'], serie['volume']
    largeur, hauteur = 620, 250
    gauche, droite, haut, bas = 48, 46, 38, 38
    zone_largeur, zone_hauteur = largeur - gauche - droite, hauteur - haut - bas
    nb_points = max(len(labels), 1)
    pas = zone_largeur / nb_points
    maximum_dh = max([*ca, *marge], default=0) or 1
    maximum_volume = max(volume, default=0) or 1
    largeur_barre = max(5, min(13, pas * .28))

    def montant_court(valeur):
        valeur = float(valeur or 0)
        return f'{valeur / 1_000:.0f} k' if valeur >= 1_000 else f'{valeur:.0f}'

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largeur} {hauteur}" role="img" aria-label="{escape(f"Performance commerciale par {libelle.lower()}")}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for index in range(5):
        y = haut + zone_hauteur * index / 4
        valeur_dh = maximum_dh * (4 - index) / 4
        valeur_volume = maximum_volume * (4 - index) / 4
        elements.extend([
            f'<line x1="{gauche}" y1="{y:.1f}" x2="{largeur - droite}" y2="{y:.1f}" stroke="#e4e6ed"/>',
            f'<text x="{gauche - 6}" y="{y + 3:.1f}" text-anchor="end" font-family="IBM Plex Mono, monospace" font-size="8" fill="#6b6f80">{montant_court(valeur_dh)} DH</text>',
            f'<text x="{largeur - droite + 6}" y="{y + 3:.1f}" font-family="IBM Plex Mono, monospace" font-size="8" fill="#6b6f80">{valeur_volume:.0f}</text>',
        ])
    elements.extend([
        f'<text x="{gauche}" y="16" font-size="8" fill="#6b6f80">CA / Marge (DH)</text>',
        f'<text x="{largeur - droite - 31}" y="16" font-size="8" fill="#6b6f80">Volume</text>',
        '<circle cx="210" cy="14" r="4" fill="#3454d1"/><text x="219" y="17" font-size="9" fill="#6b6f80">CA réalisé</text>',
        '<circle cx="305" cy="14" r="4" fill="#0e9f6e"/><text x="318" y="17" font-size="9" fill="#6b6f80">Marge</text>',
        '<circle cx="380" cy="14" r="4" fill="#cfd2dc"/><text x="389" y="17" font-size="9" fill="#6b6f80">Volume vendu</text>',
    ])
    points_marge = []
    pas_libelles = max(1, (len(labels) + 7) // 8)
    for index, label in enumerate(labels):
        centre = gauche + pas * (index + .5)
        hauteur_ca = zone_hauteur * float(ca[index] or 0) / maximum_dh
        hauteur_volume = zone_hauteur * float(volume[index] or 0) / maximum_volume
        elements.extend([
            f'<rect x="{centre - largeur_barre - 1:.1f}" y="{haut + zone_hauteur - hauteur_ca:.1f}" width="{largeur_barre:.1f}" height="{hauteur_ca:.1f}" rx="2" fill="#3454d1"/>',
            f'<rect x="{centre + 1:.1f}" y="{haut + zone_hauteur - hauteur_volume:.1f}" width="{largeur_barre:.1f}" height="{hauteur_volume:.1f}" rx="2" fill="#cfd2dc"/>',
        ])
        y_marge = haut + zone_hauteur * (1 - float(marge[index] or 0) / maximum_dh)
        points_marge.append(f'{centre:.1f},{y_marge:.1f}')
        if index % pas_libelles == 0 or index == len(labels) - 1:
            elements.append(f'<text x="{centre:.1f}" y="{hauteur - 15}" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="8" fill="#6b6f80">{escape(str(label))}</text>')
    if points_marge:
        elements.append(f'<polyline points="{" ".join(points_marge)}" fill="none" stroke="#0e9f6e" stroke-width="2.5"/>')
        for point in points_marge:
            x, y = point.split(',')
            elements.append(f'<circle cx="{x}" cy="{y}" r="2.4" fill="#0e9f6e"/>')
    elements.append('</svg>')
    return mark_safe(''.join(elements))


def graphique_repartition_svg(repartition, dimension='produit'):
    cle, libelle = {'produit': ('produit', 'Produits'), 'client': ('client', 'Clients'), 'region': ('region', 'Régions')}[dimension]
    largeur, hauteur = 620, 250
    marge_gauche, marge_droite = 156, 118
    largeur_barre = largeur - marge_gauche - marge_droite
    total = sum(float(ligne['ca'] or 0) for ligne in repartition) or 1
    maximum = total
    nombre_lignes = len(repartition)
    if nombre_lignes <= 1:
        positions_y = [125]
    else:
        espace = min(32, 170 / (nombre_lignes - 1))
        depart = (hauteur - espace * (nombre_lignes - 1)) / 2
        positions_y = [depart + index * espace for index in range(nombre_lignes)]

    def libelle_court(valeur):
        texte = str(valeur)
        return texte if len(texte) <= 23 else f'{texte[:20]}…'

    def montant_court(valeur):
        valeur = float(valeur or 0)
        if valeur >= 1_000_000:
            return f'{valeur / 1_000_000:.1f} M DH'
        if valeur >= 1_000:
            return f'{valeur / 1_000:.0f} k DH'
        return f'{valeur:.0f} DH'

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largeur} {hauteur}" role="img" aria-label="{escape(f"Répartition commerciale par {libelle.lower()}")}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<defs><linearGradient id="breakdownFill" x1="0" x2="1"><stop offset="0%" stop-color="#3454d1"/><stop offset="100%" stop-color="#5873df"/></linearGradient></defs>',
        '<circle cx="156" cy="18" r="4" fill="#3454d1"/>',
        '<text x="167" y="21" font-size="9" fill="#6b6f80">Chiffre d’affaires</text>',
        '<text x="608" y="21" text-anchor="end" font-family="IBM Plex Mono, monospace" font-size="8" fill="#a7abbb">VALEUR · PART</text>',
    ]
    for index, ligne in enumerate(repartition):
        valeur = float(ligne['ca'] or 0)
        y = positions_y[index]
        longueur = largeur_barre * valeur / maximum
        pourcentage = valeur / total * 100
        elements.extend([
            f'<rect x="4" y="{y - 5}" width="{largeur - 8}" height="24" rx="6" fill="{"#fafbfc" if index % 2 == 0 else "#ffffff"}"/>',
            f'<text x="{marge_gauche - 10}" y="{y + 10}" text-anchor="end" font-size="9" font-weight="600" fill="#4f5362">{escape(libelle_court(ligne[cle]))}</text>',
            f'<rect x="{marge_gauche}" y="{y + 1}" width="{largeur_barre:.1f}" height="12" rx="4" fill="#eef1fc"/>',
            f'<rect x="{marge_gauche}" y="{y + 1}" width="{longueur:.1f}" height="12" rx="4" fill="url(#breakdownFill)"/>',
            f'<text x="{largeur - 10}" y="{y + 10}" text-anchor="end" font-family="IBM Plex Mono, monospace" font-size="8.5" font-weight="600" fill="#12131a">{montant_court(valeur)} · {pourcentage:.0f} %</text>',
        ])
    elements.append('</svg>')
    return mark_safe(''.join(elements))


@login_required
def exporter_dashboard_pdf(request):
    global weasyprint_dll_directory_handle
    try:
        if os.name == 'nt':
            dll_directory = Path(os.environ.get('WEASYPRINT_DLL_DIRECTORY', r'C:\msys64\ucrt64\bin'))
            if dll_directory.is_dir() and weasyprint_dll_directory_handle is None:
                weasyprint_dll_directory_handle = os.add_dll_directory(str(dll_directory))
        from weasyprint import HTML
    except (ImportError, OSError):
        logger.exception('Moteur PDF indisponible')
        return HttpResponse(
            'WeasyPrint requiert les bibliotheques systeme GTK/Pango pour generer le PDF.',
            status=503,
            content_type='text/plain',
        )

    granularite = request.GET.get('granularite', 'mois')
    dimension = request.GET.get('repartition', 'produit')
    if granularite not in {'jour', 'mois', 'annee'}:
        granularite = 'mois'
    if dimension not in {'produit', 'client', 'region'}:
        dimension = 'produit'

    contexte = construire_contexte_pdf(request, granularite, dimension)
    libelles_granularite = {'jour': 'Jour', 'mois': 'Mois', 'annee': 'Annee'}
    libelles_dimension = {'produit': 'Produits', 'client': 'Clients', 'region': 'Regions'}
    contexte['graphique_performance'] = graphique_performance_svg(contexte['performance_pdf'], granularite)
    contexte['graphique_repartition'] = graphique_repartition_svg(contexte['repartition_pdf'], dimension)
    contexte['titre_performance'] = f"Performance commerciale — {libelles_granularite[granularite]}"
    contexte['titre_repartition'] = f"Répartition commerciale — {libelles_dimension[dimension]}"
    logo_path = finders.find('img/salesdecision-prism.png')
    contexte['logo_data_uri'] = (
        f"data:image/png;base64,{base64.b64encode(Path(logo_path).read_bytes()).decode('ascii')}"
        if logo_path else None
    )
    try:
        html = render_to_string('sales/dashboard_pdf.html', contexte, request=request)
        pdf = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
    except Exception:
        logger.exception('Echec de generation du rapport PDF', extra={'user_id': request.user.pk})
        return HttpResponse('Le rapport PDF n’a pas pu être généré. Réessayez dans quelques instants.', status=503, content_type='text/plain')

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="dashboard-salesdecision.pdf"'
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@configure_thresholds_required
def supprimer_ventes(request):
    if request.method == "POST":
        nb = Vente.objects.count()
        Vente.objects.all().delete()
        messages.success(request, f"{nb} vente(s) supprimee(s) avec succes.")

    return redirect("liste_ventes")
