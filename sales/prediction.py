"""Prévisions de chiffre d'affaires mensuel.

Le module privilégie un ARIMA volontairement simple quand la profondeur de
l'historique le permet, et une moyenne mobile pondérée dans les autres cas.
"""

import hashlib
import json
import math
import statistics
import warnings
from copy import deepcopy

import pandas as pd
from django.core.cache import cache
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Vente

try:
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.stattools import adfuller
except ImportError:  # Permet au dashboard de rester utilisable avant installation.
    ARIMA = None
    adfuller = None


def _expression_ca():
    """Construit l'expression ORM du chiffre d'affaires.

    Returns:
        ExpressionWrapper: expression ``quantite * prix_unitaire`` typée pour
        les agrégations Django.
    """
    return ExpressionWrapper(
        F("quantite") * F("prix_unitaire"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def _fiabilite(profondeur):
    """Évalue la fiabilité indicative d'une prévision.

    Args:
        profondeur (int): nombre de mois d'historique disponibles.

    Returns:
        str: niveau ``basse``, ``moyenne`` ou ``élevée``.
    """
    if profondeur > 18:
        return "élevée"
    if profondeur >= 6:
        return "moyenne"
    return "basse"


def _historique_mensuel(ventes):
    """Agrège des ventes en une série mensuelle continue.

    Args:
        ventes (QuerySet[Vente]): ventes auxquelles appliquer l'agrégation.

    Returns:
        pandas.Series: chiffre d'affaires mensuel, avec zéro pour tout mois
        intermédiaire sans vente.
    """
    groupes = list(
        ventes.exclude(date__isnull=True)
        .annotate(mois=TruncMonth("date"))
        .values("mois")
        .annotate(ca=Sum(_expression_ca()))
        .order_by("mois")
    )
    if not groupes:
        return pd.Series(dtype=float)

    serie = pd.Series(
        [float(groupe["ca"] or 0) for groupe in groupes],
        index=pd.DatetimeIndex([groupe["mois"] for groupe in groupes]),
        dtype=float,
    )
    mois_complets = pd.date_range(serie.index.min(), serie.index.max(), freq="MS")
    return serie.reindex(mois_complets, fill_value=0.0)


def _prevoir_mmp(historique, nb_mois):
    """Calcule une prévision récursive par moyenne mobile pondérée.

    Args:
        historique (list[float]): valeurs mensuelles observées.
        nb_mois (int): nombre de mois futurs à calculer.

    Returns:
        list[float]: valeurs prévisionnelles arrondies à deux décimales.
    """
    valeurs = list(historique)
    for _ in range(nb_mois):
        recentes = valeurs[-3:][::-1]
        poids = [0.50, 0.30, 0.20][:len(recentes)]
        total = sum(poids)
        valeurs.append(round(sum(valeur * poids[i] / total for i, valeur in enumerate(recentes)), 2))
    return valeurs[-nb_mois:]


def _erreurs_mmp(historique):
    """Retourne les erreurs d'une validation glissante à un pas."""
    return [
        float(historique[index]) - _prevoir_mmp(historique[:index], 1)[0]
        for index in range(3, len(historique))
    ]


def _intervalle_mmp(historique, previsions):
    """Estime des bornes indicatives à 95 % à partir des erreurs passées."""
    erreurs = _erreurs_mmp(historique)
    if len(erreurs) >= 2:
        ecart_type = statistics.stdev(erreurs)
    elif len(historique) >= 2:
        ecart_type = statistics.stdev(float(valeur) for valeur in historique)
    else:
        return None
    return [
        {
            "basse": round(max(0.0, valeur - 1.96 * ecart_type * math.sqrt(horizon)), 2),
            "haute": round(max(0.0, valeur + 1.96 * ecart_type * math.sqrt(horizon)), 2),
        }
        for horizon, valeur in enumerate(previsions, start=1)
    ]


def _validation_retrospective(historique):
    """Compare une prévision à un mois réellement observé, sans fuite de données."""
    if len(historique) < 4:
        return None
    realise = float(historique.iloc[-1])
    prevu = _prevoir_mmp(historique.iloc[:-1].tolist(), 1)[0]
    erreur = abs(realise - prevu)
    return {
        "mois": historique.index[-1].strftime("%m/%Y"),
        "prevu": round(prevu, 2),
        "realise": round(realise, 2),
        "ecart": round(realise - prevu, 2),
        "erreur_pct": round((erreur / abs(realise)) * 100, 2) if realise else None,
        "methode": "validation glissante MMP",
    }


def _determiner_d(serie):
    """Détermine l'ordre de différenciation ARIMA par test ADF.

    Args:
        serie (pandas.Series): série mensuelle à tester.

    Returns:
        int: ``0`` si la série est stationnaire, sinon ``1``. Une seule
        différenciation est volontairement autorisée.
    """
    # Avec moins de 12 observations, un ADF sans retard évite de consommer les
    # rares degrés de liberté restants. Le résultat reste à interpréter avec prudence.
    kwargs = {"autolag": "AIC"} if len(serie) >= 12 else {"maxlag": 0, "autolag": None}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if adfuller(serie, **kwargs)[1] < 0.05:
            return 0
    return 1


def _ajuster_arima(serie, d):
    """Ajuste le meilleur ARIMA d'une grille courte selon l'AIC.

    Args:
        serie (pandas.Series): série mensuelle à modéliser.
        d (int): ordre de différenciation retenu.

    Returns:
        statsmodels.tsa.arima.model.ARIMAResults: modèle convergé ayant l'AIC
        minimal.

    Raises:
        ValueError: si aucun modèle de la grille ne converge.
    """
    candidats = []
    for p in range(3):
        for q in range(3):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    modele = ARIMA(serie, order=(p, d, q)).fit()
                if modele.mle_retvals.get("converged", True):
                    candidats.append(modele)
            except (ValueError, ArithmeticError, FloatingPointError):
                continue
    if not candidats:
        raise ValueError("Aucun modèle ARIMA n'a convergé.")
    return min(candidats, key=lambda modele: modele.aic)


def _cle_cache_prevision(serie, nb_mois):
    """Construit une clé de cache déterministe à partir des données source.

    Args:
        serie (pandas.Series): historique mensuel agrégé.
        nb_mois (int): horizon de prévision demandé.

    Returns:
        str: clé de cache propre au contenu de la série et à son horizon.
    """
    empreinte = json.dumps(
        {
            "index": [mois.isoformat() for mois in serie.index],
            "valeurs": [float(valeur) for valeur in serie.tolist()],
            "nb_mois": nb_mois,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sales:prevision-ca:v1:{hashlib.sha256(empreinte).hexdigest()}"


def _calculer_prevision(serie, nb_mois):
    """Calcule une prévision de CA sans interroger ni alimenter le cache.

    Args:
        serie (pandas.Series): historique mensuel agrégé.
        nb_mois (int): horizon de prévision demandé.

    Returns:
        dict: méthode, mois, valeurs, fiabilité, profondeur d'historique et
        intervalle de confiance de la prévision.
    """
    if not isinstance(nb_mois, int) or nb_mois < 1:
        raise ValueError("nb_mois doit être un entier strictement positif.")

    profondeur = len(serie)
    resultat = {
        "methode": "mmp",
        "mois": [],
        "valeurs": [],
        "fiabilite": _fiabilite(profondeur),
        "profondeur_historique": profondeur,
        "intervalle_confiance": None,
        "niveau_confiance": 95,
        "validation_retrospective": _validation_retrospective(serie),
        "avertissements": [],
        "generee_le": timezone.now().isoformat(),
    }
    if serie.empty:
        resultat["avertissements"].append("Aucune vente datée : aucune prévision ne peut être calculée.")
        return resultat

    mois_sans_vente = int((serie == 0).sum())
    if mois_sans_vente:
        resultat["avertissements"].append(f"{mois_sans_vente} mois sans vente détecté(s) dans l’historique.")

    mois_futurs = pd.date_range(serie.index[-1] + pd.offsets.MonthBegin(1), periods=nb_mois, freq="MS")
    resultat["mois"] = [mois.strftime("%m/%Y") for mois in mois_futurs]

    # ARIMA est inadapté sous six mois, ou indisponible tant que statsmodels
    # n'est pas installé : la MMP reste alors déterministe et exploitable.
    if profondeur < 6 or ARIMA is None or adfuller is None:
        resultat["valeurs"] = _prevoir_mmp(serie.tolist(), nb_mois)
        resultat["intervalle_confiance"] = _intervalle_mmp(serie.tolist(), resultat["valeurs"])
        resultat["avertissements"].append("Historique limité : une moyenne mobile est utilisée à la place d’ARIMA.")
        return resultat

    try:
        d = _determiner_d(serie)
        modele = _ajuster_arima(serie, d)
        prevision = modele.get_forecast(steps=nb_mois)
        bornes = prevision.conf_int(alpha=0.05)
        resultat.update({
            "methode": "arima",
            "valeurs": [round(max(0.0, float(valeur)), 2) for valeur in prevision.predicted_mean],
            "intervalle_confiance": [
                {"basse": round(max(0.0, float(ligne[0])), 2), "haute": round(max(0.0, float(ligne[1])), 2)}
                for ligne in bornes.to_numpy()
            ],
        })
    except Exception:
        # Une série courte ou dégénérée peut empêcher la convergence ; le
        # repli garantit que l'affichage et les décisions métier restent actifs.
        resultat["valeurs"] = _prevoir_mmp(serie.tolist(), nb_mois)
        resultat["intervalle_confiance"] = _intervalle_mmp(serie.tolist(), resultat["valeurs"])
        resultat["avertissements"].append("ARIMA n’a pas convergé : prévision calculée par moyenne mobile.")
    return resultat


def predire_ca_pour_ventes(ventes, nb_mois=3, force_refresh=False):
    """Prévoit le CA d'un queryset de ventes en réutilisant le résultat stable.

    La clé dépend de l'historique mensuel réellement modélisé et de l'horizon,
    pas de l'URL ou des filtres. Ainsi, une requête répétée ne réajuste pas
    ARIMA ; une modification des données qui affecte la série génère une clé
    différente et force naturellement un nouveau calcul.

    Args:
        ventes (QuerySet[Vente]): ventes, éventuellement filtrées, à prévoir.
        nb_mois (int): nombre de mois futurs à prévoir, ``3`` par défaut.

    Returns:
        dict: méthode, mois, valeurs, fiabilité, profondeur d'historique et
        intervalle de confiance de la prévision.
    """
    if not isinstance(nb_mois, int) or nb_mois < 1:
        raise ValueError("nb_mois doit être un entier strictement positif.")

    serie = _historique_mensuel(ventes)
    cle_cache = _cle_cache_prevision(serie, nb_mois)
    if force_refresh:
        cache.delete(cle_cache)
    resultat = cache.get(cle_cache)
    if resultat is None:
        resultat = _calculer_prevision(serie, nb_mois)
        # La clé porte l'empreinte des données : aucun TTL n'est nécessaire
        # pour la fraîcheur et une modification pertinente force une nouvelle
        # entrée. Le backend applique par ailleurs ses limites de capacité.
        cache.set(cle_cache, resultat, timeout=None)
    return deepcopy(resultat)


def predire_ca(nb_mois=3):
    """Prévoit le CA mensuel global.

    Args:
        nb_mois (int): nombre de mois futurs à prévoir, 3 par défaut.

    Returns:
        dict: ``methode`` (``arima`` ou ``mmp``), ``mois`` (list[str]),
        ``valeurs`` (list[float]), ``fiabilite`` (str),
        ``profondeur_historique`` (int) et ``intervalle_confiance``
        (list[dict] ou ``None``).

    Example:
        >>> predire_ca(3)["methode"]
        'mmp'
    """
    return predire_ca_pour_ventes(Vente.objects.all(), nb_mois=nb_mois)
