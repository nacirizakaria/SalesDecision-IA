"""Décorateurs de permissions réutilisables par les futurs modules Sales."""

from functools import wraps

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied

DECIDEUR_GROUP = 'Décideur'
BUSINESS_USER_GROUP = 'Utilisateur de métiers'


# À appliquer à la future vue de configuration des seuils. La permission est
# attribuée par la migration au seul groupe « Décideur ».
configure_thresholds_required = permission_required(
    'sales.configure_thresholds',
    raise_exception=True,
)

import_sales_required = permission_required(
    'sales.import_sales',
    raise_exception=True,
)


def administrator_required(view):
    """Réserve une vue aux comptes d'administration Django actifs."""

    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped
