from django.db import migrations


OLD_BUSINESS_USER_GROUP = 'Utilisateur métier'
BUSINESS_USER_GROUP = 'Utilisateur de métiers'


def rename_business_user_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    old_group = Group.objects.filter(name=OLD_BUSINESS_USER_GROUP).first()
    new_group, _ = Group.objects.get_or_create(name=BUSINESS_USER_GROUP)

    if old_group and old_group.pk != new_group.pk:
        new_group.user_set.add(*old_group.user_set.all())
        old_group.delete()


def restore_business_user_group_name(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    group = Group.objects.filter(name=BUSINESS_USER_GROUP).first()
    if group:
        group.name = OLD_BUSINESS_USER_GROUP
        group.save(update_fields=['name'])


class Migration(migrations.Migration):
    dependencies = [('sales', '0004_roles_and_threshold_permission')]

    operations = [migrations.RunPython(rename_business_user_group, restore_business_user_group_name)]
