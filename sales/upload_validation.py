"""Validation centralisée et sûre des fichiers de ventes importés."""

from pathlib import Path
from zipfile import BadZipFile

import pandas as pd
from django.conf import settings
from django.core.exceptions import ValidationError
from pandas.errors import EmptyDataError, ParserError


ALLOWED_EXTENSIONS = {'.csv', '.xlsx', '.xls'}
XLSX_SIGNATURE = b'PK'
XLS_SIGNATURE = bytes.fromhex('D0CF11E0A1B11AE1')


class SalesUploadError(Exception):
    """Erreur fonctionnelle affichable, sans détail technique interne."""


def validate_sales_file(uploaded_file):
    """Valide l'extension, la taille et la signature avant le parsing."""
    extension = Path(uploaded_file.name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            'Format non autorisé. Utilisez un fichier CSV, XLSX ou XLS.'
        )

    if uploaded_file.size > settings.MAX_UPLOAD_SIZE_BYTES:
        raise ValidationError(
            f'Le fichier dépasse la taille maximale autorisée de '
            f'{settings.MAX_UPLOAD_SIZE_MB} Mo.'
        )
    if uploaded_file.size == 0:
        raise ValidationError('Le fichier est vide. Ajoutez des données puis réessayez.')

    header = uploaded_file.read(8)
    uploaded_file.seek(0)
    if extension == '.xlsx' and not header.startswith(XLSX_SIGNATURE):
        raise ValidationError(
            'Le fichier XLSX est invalide ou corrompu. Exportez-le à nouveau.'
        )
    if extension == '.xls' and header != XLS_SIGNATURE:
        raise ValidationError(
            'Le fichier XLS est invalide ou corrompu. Exportez-le à nouveau.'
        )
    if extension == '.csv' and b'\x00' in header:
        raise ValidationError(
            'Le fichier CSV est invalide ou corrompu. Exportez-le à nouveau.'
        )
    return uploaded_file


def read_sales_file(uploaded_file):
    """Lit le fichier et transforme les erreurs techniques en messages français."""
    extension = Path(uploaded_file.name).suffix.lower()
    uploaded_file.seek(0)
    try:
        dataframe = (
            pd.read_csv(uploaded_file)
            if extension == '.csv'
            else pd.read_excel(uploaded_file)
        )
    except EmptyDataError as exc:
        raise SalesUploadError(
            'Le fichier est vide ou ne contient aucune ligne d’en-tête.'
        ) from exc
    except (BadZipFile, ParserError, UnicodeDecodeError, ValueError, OSError) as exc:
        raise SalesUploadError(
            'Le fichier est corrompu ou son format est invalide. '
            'Exportez-le à nouveau puis réessayez.'
        ) from exc
    except Exception as exc:
        # Ne jamais exposer les détails internes de pandas/openpyxl.
        raise SalesUploadError(
            'Impossible de lire ce fichier. Vérifiez son format puis réessayez.'
        ) from exc

    if len(dataframe.columns) == 0:
        raise SalesUploadError(
            'Le fichier ne contient aucune ligne d’en-tête exploitable.'
        )
    if dataframe.empty:
        raise SalesUploadError(
            'Le fichier contient uniquement des en-têtes et aucune donnée.'
        )
    return dataframe
