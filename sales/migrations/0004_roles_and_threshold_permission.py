from django.db import migrations


DECIDEUR_GROUP = 'Décideur'
BUSINESS_USER_GROUP = 'Utilisateur métier'
THRESHOLD_PERMISSION = 'configure_thresholds'


def create_roles_and_permission(apps, schema_editor):
    """Crée des rôles idempotents et réserve la configuration aux Décideurs."""
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')

    content_type, _ = ContentType.objects.get_or_create(
        app_label='sales',
        model='vente',
    )
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename=THRESHOLD_PERMISSION,
        defaults={'name': 'Peut configurer les seuils d’alerte'},
    )

    decideur, _ = Group.objects.get_or_create(name=DECIDEUR_GROUP)
    Group.objects.get_or_create(name=BUSINESS_USER_GROUP)
    decideur.permissions.add(permission)


def remove_roles_and_permission(apps, schema_editor):
    """Retire uniquement l'affectation; ne supprime pas les groupes existants."""
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')

    try:
        decideur = Group.objects.get(name=DECIDEUR_GROUP)
        permission = Permission.objects.get(
            content_type__app_label='sales',
            codename=THRESHOLD_PERMISSION,
        )
    except (Group.DoesNotExist, Permission.DoesNotExist):
        return

    decideur.permissions.remove(permission)


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0003_vente_client_nullable_fields'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='vente',
            options={
                'permissions': [
                    ('configure_thresholds', 'Peut configurer les seuils d’alerte'),
                ],
            },
        ),
        migrations.RunPython(create_roles_and_permission, remove_roles_and_permission),
    ]
