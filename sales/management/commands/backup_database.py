import gzip
from datetime import datetime, timedelta
from io import StringIO

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command
from django.utils import timezone


class Command(BaseCommand):
    help = 'Crée une sauvegarde Django compressée et chiffrée, puis applique la rétention.'

    def add_arguments(self, parser):
        parser.add_argument('--retention-days', type=int, default=14)

    def handle(self, *args, **options):
        if not settings.BACKUP_ENCRYPTION_KEY:
            raise CommandError('BACKUP_ENCRYPTION_KEY est obligatoire.')
        try:
            fernet = Fernet(settings.BACKUP_ENCRYPTION_KEY.encode())
        except (ValueError, InvalidToken) as error:
            raise CommandError('BACKUP_ENCRYPTION_KEY doit être une clé Fernet valide.') from error

        output = StringIO()
        call_command(
            'dumpdata',
            exclude=['sessions.session', 'admin.logentry', 'contenttypes'],
            natural_foreign=True,
            natural_primary=True,
            stdout=output,
        )
        compressed = gzip.compress(output.getvalue().encode('utf-8'), compresslevel=9)
        encrypted = fernet.encrypt(compressed)

        settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
        target = settings.BACKUP_DIR / f'salesdecision-{timestamp}.json.gz.fernet'
        target.write_bytes(encrypted)

        cutoff = timezone.now() - timedelta(days=max(options['retention_days'], 1))
        removed = 0
        for backup in settings.BACKUP_DIR.glob('salesdecision-*.json.gz.fernet'):
            if datetime.fromtimestamp(
                backup.stat().st_mtime, tz=timezone.get_current_timezone(),
            ) < cutoff:
                backup.unlink()
                removed += 1

        self.stdout.write(self.style.SUCCESS(
            f'Sauvegarde chiffrée créée: {target} ({removed} ancienne(s) supprimée(s)).'
        ))
