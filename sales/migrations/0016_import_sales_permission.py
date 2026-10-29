from django.db import migrations


DECIDEUR_GROUP = 'Décideur'
BUSINESS_USER_GROUP = 'Utilisateur de métiers'
PERMISSION_CODENAME = 'import_sales'


def add_import_permission(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')

    content_type, _ = ContentType.objects.get_or_create(
        app_label='sales',
        model='vente',
    )
    permission, _ = Permission.objects.get_or_create(
        codename=PERMISSION_CODENAME,
        content_type=content_type,
        defaults={'name': 'Peut importer des fichiers de ventes'},
    )
    for group_name in (DECIDEUR_GROUP, BUSINESS_USER_GROUP):
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.add(permission)


def remove_import_permission(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    permission = Permission.objects.filter(
        codename=PERMISSION_CODENAME,
        content_type__app_label='sales',
    ).first()
    if permission:
        permission.group_set.clear()
        permission.delete()


class Migration(migrations.Migration):
    dependencies = [
        ('sales', '0015_assistant_pipeline_metrics_and_sales_indexes'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='vente',
            options={
                'permissions': [
                    ('import_sales', 'Peut importer des fichiers de ventes'),
                    ('configure_thresholds', 'Peut configurer les seuils d’alerte'),
                ],
            },
        ),
        migrations.RunPython(add_import_permission, remove_import_permission),
    ]
