from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('sales', '0012_delete_adminmfa'),
    ]

    operations = [
        migrations.CreateModel(
            name='ChatInteraction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question', models.CharField(max_length=500)),
                ('answer', models.TextField()),
                ('provider', models.CharField(max_length=32)),
                ('provider_response_id', models.CharField(blank=True, max_length=255)),
                ('helpful', models.BooleanField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sales_chat_interactions', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='LearnedChatExample',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('normalized_question', models.CharField(db_index=True, max_length=500)),
                ('active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('interaction', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='learned_example', to='sales.chatinteraction')),
            ],
            options={'ordering': ['-updated_at']},
        ),
    ]
