from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from sales.auth_views import (
    ProvisionedLoginView,
    ProvisionedPasswordChangeDoneView,
    ProvisionedPasswordChangeView,
)
from sales.views import health_check

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='dashboard', permanent=False), name='home'),
    path('admin/', admin.site.urls),
    path('accounts/login/', ProvisionedLoginView.as_view(), name='login'),
    path(
        'accounts/activation/change-password/',
        ProvisionedPasswordChangeView.as_view(),
        name='provisioning_password_change',
    ),
    path(
        'accounts/activation/complete/',
        ProvisionedPasswordChangeDoneView.as_view(),
        name='provisioning_password_change_done',
    ),
    path('accounts/', include('django.contrib.auth.urls')),
    path('sales/', include('sales.urls')),
    path('health/', health_check, name='health'),
]
