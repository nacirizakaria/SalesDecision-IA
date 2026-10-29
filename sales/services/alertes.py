from decimal import Decimal

from sales.models import SeuilAlerte


# Chaque seuil est relatif a l'historique de l'entreprise. Le module ARIMA est
# volontairement absent tant que les previsions passees ne sont pas stockees.
SEUILS_PAR_DEFAUT = (
    ('baisse_ca', "Evolution du chiffre d'affaires", 'ca', 'ca', -5, -15,
     'Le chiffre d’affaires recule par rapport a sa reference historique.'),
    ('baisse_marge', 'Evolution de la marge', 'ca', 'marge', -8, -20,
     'La marge recule par rapport a sa reference historique.'),
    ('baisse_panier', 'Evolution du panier moyen', 'ca', 'panier', -8, -15,
     'Le panier moyen recule par rapport a sa reference historique.'),
    ('baisse_volume', 'Evolution du volume vendu', 'volume', 'volume', -10, -20,
     'Le volume vendu recule par rapport a sa reference historique.'),
)

INDICATEURS = {code: champ for code, _nom, _type, champ, _orange, _rouge, _description in SEUILS_PAR_DEFAUT}


def initialiser_seuils_par_defaut():
    """Crée les règles manquantes en une lecture, sans écraser un choix utilisateur."""
    codes = [configuration[0] for configuration in SEUILS_PAR_DEFAUT]
    seuils_existants = SeuilAlerte.objects.in_bulk(codes, field_name='code_alerte')
    seuils_a_creer = []

    for code, nom, indicateur, _champ, orange, rouge, description in SEUILS_PAR_DEFAUT:
        seuil = seuils_existants.get(code)
        if seuil is None:
            seuils_a_creer.append(SeuilAlerte(
                code_alerte=code,
                nom_kpi=nom,
                type_indicateur=indicateur,
                type_comparaison=SeuilAlerte.TypeComparaison.BAISSE_PCT,
                reference_comparaison=SeuilAlerte.ReferenceComparaison.MOYENNE_MOBILE_3,
                seuil_orange=orange,
                seuil_rouge=rouge,
                couleur=SeuilAlerte.Couleur.ORANGE,
                description=description,
                actif=True,
            ))
            continue

        mises_a_jour = {}
        if not seuil.nom_kpi:
            mises_a_jour['nom_kpi'] = nom
        if seuil.seuil_orange is None:
            mises_a_jour['seuil_orange'] = orange
        if seuil.seuil_rouge is None:
            mises_a_jour['seuil_rouge'] = rouge
        if seuil.type_comparaison == SeuilAlerte.TypeComparaison.INFERIEUR:
            mises_a_jour['type_comparaison'] = SeuilAlerte.TypeComparaison.BAISSE_PCT
        if not seuil.description:
            mises_a_jour['description'] = description
        if mises_a_jour:
            SeuilAlerte.objects.filter(pk=seuil.pk).update(**mises_a_jour)

    if seuils_a_creer:
        # ``ignore_conflicts`` protège aussi deux premiers chargements concurrents.
        SeuilAlerte.objects.bulk_create(seuils_a_creer, ignore_conflicts=True)


def evaluer_alertes(evolution_pct: float, type_indicateur: str) -> dict:
    """Evaluation generique min/max conservee pour les integrations existantes."""
    evolution = Decimal(str(evolution_pct))
    seuils = SeuilAlerte.objects.filter(type_indicateur=type_indicateur, actif=True).order_by('id')
    for seuil in seuils:
        if seuil.seuil_min is not None and evolution < seuil.seuil_min:
            return {'niveau': seuil.couleur, 'code_alerte': seuil.code_alerte, 'evolution': evolution_pct}
        if seuil.seuil_max is not None and evolution > seuil.seuil_max:
            return {'niveau': seuil.couleur, 'code_alerte': seuil.code_alerte, 'evolution': evolution_pct}
    return {'niveau': 'vert', 'code_alerte': None, 'evolution': evolution_pct}


def evaluer_seuil_kpi(seuil: SeuilAlerte, valeur):
    if valeur is None or not seuil.actif:
        return None
    valeur = Decimal(str(valeur))
    if seuil.seuil_rouge is not None and valeur <= seuil.seuil_rouge:
        return 'rouge'
    if seuil.seuil_orange is not None and valeur <= seuil.seuil_orange:
        return 'orange'
    return 'vert'


def variation_par_rapport_a_reference(serie_mensuelle, reference, champ='ca'):
    """Retourne le reel, la reference et la variation d'un indicateur mensuel."""
    valeurs = [Decimal(str(point.get(champ) or 0)) for point in serie_mensuelle]
    if len(valeurs) < 2:
        return None, None, None, None

    valeur_reelle = valeurs[-1]
    historique = valeurs[:-1]
    if reference == SeuilAlerte.ReferenceComparaison.MOYENNE_MOBILE_3 and len(historique) >= 3:
        valeur_reference = sum(historique[-3:]) / Decimal('3')
        libelle_reference = 'moyenne des 3 mois precedents'
    else:
        valeur_reference = historique[-1]
        libelle_reference = 'mois precedent'

    if not valeur_reference:
        return valeur_reelle, valeur_reference, None, libelle_reference
    variation = ((valeur_reelle - valeur_reference) / valeur_reference) * Decimal('100')
    return valeur_reelle, valeur_reference, variation.quantize(Decimal('0.01')), libelle_reference


def etats_alertes_dashboard(kpis):
    """Expose un etat utilisable pour chaque regle de la page de configuration."""
    initialiser_seuils_par_defaut()
    seuils = SeuilAlerte.objects.filter(code_alerte__in=INDICATEURS).order_by('code_alerte')
    etats = {}
    for seuil in seuils:
        reel, reference, variation, libelle = variation_par_rapport_a_reference(
            kpis['ca_par_mois'], seuil.reference_comparaison, INDICATEURS[seuil.code_alerte],
        )
        etats[seuil.code_alerte] = {
            'evaluee': variation is not None,
            'variation': variation,
            'reference': reference,
            'libelle_reference': libelle,
        }
    return etats


def construire_alertes_dashboard(kpis, prediction_ca=None):
    """Construit les alertes rouges et orange pour les quatre KPI disponibles."""
    initialiser_seuils_par_defaut()
    alertes = []
    seuils = SeuilAlerte.objects.filter(actif=True, code_alerte__in=INDICATEURS).order_by('code_alerte')
    for seuil in seuils:
        reel, reference, variation, libelle_reference = variation_par_rapport_a_reference(
            kpis['ca_par_mois'], seuil.reference_comparaison, INDICATEURS[seuil.code_alerte],
        )
        if reel is None:
            continue
        if seuil.code_alerte == 'baisse_ca' and seuil.seuil_minimum_absolu is not None and reel <= seuil.seuil_minimum_absolu:
            alertes.append({
                'niveau': 'rouge', 'nom_kpi': seuil.nom_kpi, 'valeur': reel,
                'seuil': seuil.seuil_minimum_absolu, 'unite': 'DH',
                'message': 'Le chiffre d’affaires est sous le plancher minimum defini pour votre entreprise.',
                'code_alerte': seuil.code_alerte, 'reference': None,
                'action_url': '#performanceChart', 'action_label': 'Analyser la performance',
            })
            continue

        niveau = evaluer_seuil_kpi(seuil, variation)
        if niveau not in {'orange', 'rouge'}:
            continue
        seuil_declencheur = seuil.seuil_rouge if niveau == 'rouge' else seuil.seuil_orange
        alertes.append({
            'niveau': niveau,
            'nom_kpi': seuil.nom_kpi or seuil.code_alerte,
            'valeur': variation,
            'seuil': seuil_declencheur,
            'unite': '%',
            'message': seuil.description or 'Seuil d’alerte atteint.',
            'code_alerte': seuil.code_alerte,
            'reference': reference,
            'libelle_reference': libelle_reference,
            'action_url': '#performanceChart',
            'action_label': 'Voir l’analyse',
        })
    return alertes
