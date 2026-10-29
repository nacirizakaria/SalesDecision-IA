from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, PasswordChangeDoneView, PasswordChangeView
from django.db import transaction
from django.urls import reverse_lazy
from django.utils import timezone

from .models import UserProvisioningAudit
from .security import clear_login_failures, client_ip, login_is_locked, record_login_failure


class ProvisionedAuthenticationForm(AuthenticationForm):
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields['username'].label = 'Identifiant'
        self.fields['password'].label = 'Mot de passe'

    def clean(self):
        username = self.data.get('username', '')
        ip_address = client_ip(self.request)
        if login_is_locked(username, ip_address):
            raise forms.ValidationError(
                'Trop de tentatives. Réessayez dans 15 minutes.',
                code='login_locked',
            )
        try:
            cleaned_data = super().clean()
        except forms.ValidationError:
            record_login_failure(username, ip_address)
            raise
        clear_login_failures(username, ip_address)
        return cleaned_data

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        provisioning = getattr(user, 'provisioning', None)
        if (
            provisioning
            and provisioning.must_change_password
            and provisioning.temporary_password_expires_at <= timezone.now()
        ):
            raise forms.ValidationError(
                "Ce mot de passe temporaire a expiré. Contactez l'administrateur qui a créé le compte.",
                code='temporary_password_expired',
            )


class ProvisionedLoginView(LoginView):
    authentication_form = ProvisionedAuthenticationForm
    template_name = 'registration/login.html'


class ProvisionedPasswordChangeView(PasswordChangeView):
    template_name = 'sales/password_change_form.html'
    success_url = reverse_lazy('provisioning_password_change_done')

    def form_valid(self, form):
        provisioning = getattr(self.request.user, 'provisioning', None)
        if (
            provisioning
            and provisioning.must_change_password
            and provisioning.temporary_password_expires_at <= timezone.now()
        ):
            form.add_error(None, 'Le mot de passe temporaire a expiré.')
            return self.form_invalid(form)

        with transaction.atomic():
            response = super().form_valid(form)
            if provisioning and provisioning.must_change_password:
                provisioning.must_change_password = False
                provisioning.password_changed_at = timezone.now()
                provisioning.save(update_fields=['must_change_password', 'password_changed_at'])
                UserProvisioningAudit.objects.create(
                    actor=self.request.user,
                    target_user=self.request.user,
                    action=UserProvisioningAudit.Action.PASSWORD_CHANGED,
                )
        self.request.session.pop('temporary_password_expired', None)
        return response


class ProvisionedPasswordChangeDoneView(PasswordChangeDoneView):
    template_name = 'sales/password_change_done.html'
