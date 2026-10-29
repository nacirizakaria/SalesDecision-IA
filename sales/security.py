import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import LoginThrottle


def client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', ''))[:64]


def throttle_key(username, ip_address):
    normalized = f'{username.strip().lower()}|{ip_address}'
    return hmac.new(
        settings.SECRET_KEY.encode(), normalized.encode(), hashlib.sha256,
    ).hexdigest()


def get_login_throttle(username, ip_address):
    return LoginThrottle.objects.filter(key_hash=throttle_key(username, ip_address)).first()


def login_is_locked(username, ip_address):
    throttle = get_login_throttle(username, ip_address)
    return bool(throttle and throttle.locked_until and throttle.locked_until > timezone.now())


@transaction.atomic
def record_login_failure(username, ip_address):
    now = timezone.now()
    key = throttle_key(username, ip_address)
    throttle, _ = LoginThrottle.objects.select_for_update().get_or_create(key_hash=key)
    window = timedelta(seconds=settings.LOGIN_FAILURE_WINDOW_SECONDS)
    if throttle.window_started_at + window <= now:
        throttle.failed_attempts = 0
        throttle.window_started_at = now
        throttle.locked_until = None
    throttle.failed_attempts += 1
    if throttle.failed_attempts >= settings.LOGIN_MAX_FAILURES:
        throttle.locked_until = now + timedelta(seconds=settings.LOGIN_LOCK_SECONDS)
    throttle.save()


def clear_login_failures(username, ip_address):
    LoginThrottle.objects.filter(key_hash=throttle_key(username, ip_address)).delete()
