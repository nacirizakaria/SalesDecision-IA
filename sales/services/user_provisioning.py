import secrets
import string
import unicodedata
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from sales.models import UserProvisioning, UserProvisioningAudit


PASSWORD_LENGTH = 20
TEMPORARY_PASSWORD_TTL = timedelta(minutes=30)
USERNAME_SUFFIX_ALPHABET = '23456789abcdefghjkmnpqrstuvwxyz'


@dataclass(frozen=True)
class ProvisionedCredentials:
    user_id: int
    username: str
    temporary_password: str
    expires_at: object


def _normalize_name(value):
    ascii_value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
    return ''.join(character for character in ascii_value.lower() if character.isalnum())


def _random_chars(alphabet, length):
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def generate_temporary_password(length=PASSWORD_LENGTH):
    if length < 15:
        raise ValueError('Un mot de passe temporaire doit contenir au moins 15 caracteres.')
    groups = (string.ascii_uppercase, string.ascii_lowercase, string.digits, '!@#$%*-_+=')
    characters = [secrets.choice(group) for group in groups]
    alphabet = ''.join(groups)
    characters.extend(secrets.choice(alphabet) for _ in range(length - len(characters)))
    secrets.SystemRandom().shuffle(characters)
    return ''.join(characters)


def _username_candidate(first_name, last_name):
    first = _normalize_name(first_name)[:1] or 'u'
    last = _normalize_name(last_name)[:20] or 'user'
    return f'{first}.{last}-{_random_chars(USERNAME_SUFFIX_ALPHABET, 5)}'


def provision_user(*, creator, first_name, last_name, email, group):
    """Crée atomiquement le compte; le secret ne quitte pas la mémoire applicative."""
    User = get_user_model()
    temporary_password = generate_temporary_password()
    expires_at = timezone.now() + TEMPORARY_PASSWORD_TTL

    for _ in range(10):
        username = _username_candidate(first_name, last_name)
        try:
            with transaction.atomic():
                user = User(
                    username=username, first_name=first_name, last_name=last_name,
                    email=email, is_active=True,
                )
                user.set_password(temporary_password)
                user.save()
                user.groups.set([group])
                UserProvisioning.objects.create(
                    user=user, created_by=creator, temporary_password_expires_at=expires_at,
                )
                UserProvisioningAudit.objects.create(
                    actor=creator, target_user=user,
                    action=UserProvisioningAudit.Action.CREATED,
                )
            return ProvisionedCredentials(
                user_id=user.pk, username=username,
                temporary_password=temporary_password, expires_at=expires_at,
            )
        except IntegrityError:
            continue
    raise RuntimeError("Impossible d'allouer un identifiant unique.")
