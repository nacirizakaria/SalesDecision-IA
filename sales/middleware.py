from django.shortcuts import redirect
from django.utils import timezone

from .models import UserProvisioning

PASSWORD_CHANGE_PATH = '/accounts/activation/change-password/'
PASSWORD_CHANGE_DONE_PATH = '/accounts/activation/complete/'


class TemporaryPasswordMiddleware:
    """Bloque la navigation tant que le secret initial n'est pas remplacé."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                provisioning = request.user.provisioning
            except UserProvisioning.DoesNotExist:
                provisioning = None

            if provisioning and provisioning.must_change_password:
                request.session['temporary_password_expired'] = (
                    provisioning.temporary_password_expires_at <= timezone.now()
                )
                allowed_paths = {
                    PASSWORD_CHANGE_PATH,
                    PASSWORD_CHANGE_DONE_PATH,
                    '/accounts/logout/',
                }
                if request.path not in allowed_paths:
                    return redirect(PASSWORD_CHANGE_PATH)
        return self.get_response(request)
