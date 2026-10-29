from django.urls import path
from . import views

urlpatterns = [
    path('import/', views.import_ventes, name='import_ventes'),
    path('liste/', views.liste_ventes, name='liste_ventes'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/recommendation-chat/', views.recommendation_chat, name='recommendation_chat'),
    path('dashboard/recommendation-chat/stream/', views.recommendation_chat_stream, name='recommendation_chat_stream'),
    path('dashboard/recommendation-chat/clear/', views.recommendation_chat_clear, name='recommendation_chat_clear'),
    path('dashboard/recommendation-chat/feedback/', views.recommendation_chat_feedback, name='recommendation_chat_feedback'),
    path('dashboard/export-pdf/', views.exporter_dashboard_pdf, name='dashboard_pdf'),
    path('alertes/configuration/', views.configurer_alertes, name='configurer_alertes'),
    path('users/create/', views.create_user, name='create_user'),
    path('security/', views.security_users, name='security_users'),
    path('security/users/<int:user_id>/delete/', views.delete_user_account, name='delete_user_account'),

    path(
        'supprimer-ventes/',
        views.supprimer_ventes,
        name='supprimer_ventes'
    ),
]
