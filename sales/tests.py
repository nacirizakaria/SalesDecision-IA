from datetime import date
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from .models import SeuilAlerte, Vente
from .prediction import predire_ca_pour_ventes
from .services.alertes import construire_alertes_dashboard, initialiser_seuils_par_defaut
from .views import calculer_kpis


class AuthenticatedTestCase(TestCase):
    """Les vues Sales sont privées : les tests métier utilisent un utilisateur connecté."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='analyste', password='mot-de-passe-fort')
        self.client.force_login(self.user)


class ImportVentesTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.user.groups.add(Group.objects.get(name='Décideur'))

    def importer_csv(self, contenu):
        fichier = SimpleUploadedFile('ventes.csv', contenu.encode('utf-8'), content_type='text/csv')
        return self.client.post(reverse('import_ventes'), {'fichier': fichier})

    def test_import_avec_client(self):
        response = self.importer_csv(
            'date,client,produit,quantite,prix_unitaire,cout_unitaire,region\n'
            '2026-01-15,Client A,Ordinateur,2,1000,700,Casablanca\n'
        )

        self.assertEqual(response.status_code, 200)
        vente = Vente.objects.first()
        self.assertEqual(Vente.objects.count(), 1)
        self.assertEqual(vente.client, 'Client A')
        self.assertEqual(vente.ca(), 2000)
        self.assertEqual(vente.marge(), 600)

    def test_import_colonne_manquante_continue(self):
        response = self.importer_csv(
            'date,produit,quantite,prix_unitaire\n'
            '2026-01-15,Ordinateur,2,1000\n'
        )

        self.assertContains(response, '1 vente(s)')
        self.assertContains(response, 'Colonnes absentes')
        vente = Vente.objects.first()
        self.assertIsNone(vente.client)
        self.assertEqual(vente.cout_unitaire, 0)
        self.assertEqual(vente.region, None)

    def test_import_date_manquante_continue(self):
        response = self.importer_csv(
            'client,produit,quantite,prix_unitaire,cout_unitaire\n'
            'Client B,Souris,5,80,50\n'
        )

        self.assertContains(response, '1 vente(s)')
        vente = Vente.objects.first()
        self.assertIsNone(vente.date)
        self.assertEqual(vente.client, 'Client B')

    def test_import_accepte_alias_colonnes_varies(self):
        response = self.importer_csv(
            'Sale Date,Customer Name,Item,Qty,Unit Price,Unit Cost,City\n'
            '2026-03-15,Client C,Clavier,3,200,120,Tanger\n'
        )

        self.assertContains(response, '1 vente(s)')
        vente = Vente.objects.first()
        self.assertEqual(vente.date, date(2026, 3, 15))
        self.assertEqual(vente.client, 'Client C')
        self.assertEqual(vente.produit, 'Clavier')
        self.assertEqual(vente.quantite, 3)
        self.assertEqual(vente.ca(), 600)
        self.assertEqual(vente.marge(), 240)
        self.assertEqual(vente.region, 'Tanger')

    def test_import_multi_fichiers_avec_ca_cl_qte_marge(self):
        response_1 = self.importer_csv(
            'Date,CL,Designation,QTE,CA,Marge,Region,Objectif,N°\n'
            '2026-04-01,Client D,Ecran,2,3000,700,Fes,5000,F-001\n'
        )
        response_2 = self.importer_csv(
            'Date facture,Client,Code produit,Quantite vendue,Prix moyen,Cout moyen,Agence\n'
            '2026-04-02,Client E,Station,1,8000,6200,Marrakech\n'
        )

        self.assertContains(response_1, '1 vente(s)')
        self.assertContains(response_2, '1 vente(s)')
        self.assertEqual(Vente.objects.count(), 2)

        vente_ca = Vente.objects.get(client='Client D')
        self.assertEqual(vente_ca.produit, 'Ecran')
        self.assertEqual(vente_ca.quantite, 2)
        self.assertEqual(vente_ca.prix_unitaire, 1500)
        self.assertEqual(vente_ca.cout_unitaire, 1150)
        self.assertEqual(vente_ca.ca(), 3000)
        self.assertEqual(vente_ca.marge(), 700)
        self.assertEqual(vente_ca.region, 'Fes')

        vente_prix = Vente.objects.get(client='Client E')
        self.assertEqual(vente_prix.produit, 'Station')
        self.assertEqual(vente_prix.ca(), 8000)
        self.assertEqual(vente_prix.marge(), 1800)
        self.assertEqual(vente_prix.region, 'Marrakech')

    def test_import_refuse_un_fichier_vide_sans_planter(self):
        fichier = SimpleUploadedFile('ventes.csv', b'', content_type='text/csv')

        response = self.client.post(reverse('import_ventes'), {'fichier': fichier})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'vide')
        self.assertEqual(Vente.objects.count(), 0)

    def test_import_refuse_un_fichier_avec_entetes_seuls(self):
        response = self.importer_csv(
            'date,client,produit,quantite,prix_unitaire,cout_unitaire,region\n'
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'uniquement des en-têtes')
        self.assertEqual(Vente.objects.count(), 0)

    def test_import_refuse_un_fichier_trop_volumineux(self):
        contenu = b'a' * (10 * 1024 * 1024 + 1)
        fichier = SimpleUploadedFile('ventes.csv', contenu, content_type='text/csv')

        response = self.client.post(reverse('import_ventes'), {'fichier': fichier})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'taille maximale autorisée de 10 Mo')
        self.assertEqual(Vente.objects.count(), 0)

    def test_import_refuse_un_xlsx_corrompu_sans_detail_technique(self):
        fichier = SimpleUploadedFile(
            'ventes.xlsx',
            b'ceci-n-est-pas-un-fichier-excel',
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

        response = self.client.post(reverse('import_ventes'), {'fichier': fichier})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'invalide ou corrompu')
        self.assertNotContains(response, 'BadZipFile')
        self.assertEqual(Vente.objects.count(), 0)


class KpiDashboardTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        Vente.objects.create(
            date=date(2026, 1, 10),
            client='Client A',
            produit='Ordinateur',
            quantite=2,
            prix_unitaire=1000,
            cout_unitaire=700,
            region='Casablanca',
        )
        Vente.objects.create(
            date=date(2026, 1, 11),
            client='Client B',
            produit='Souris',
            quantite=10,
            prix_unitaire=80,
            cout_unitaire=50,
            region='Rabat',
        )
        Vente.objects.create(
            date=date(2026, 2, 10),
            client='Client A',
            produit='Ordinateur',
            quantite=1,
            prix_unitaire=1200,
            cout_unitaire=800,
            region='Casablanca',
        )

    def test_kpis_ca_journalier_mensuel_annuel_client_volume(self):
        kpis = calculer_kpis()

        self.assertEqual(kpis['ca_total'], 4000)
        self.assertEqual(kpis['client_top']['client'], 'Client A')
        self.assertEqual(kpis['produit_top']['produit'], 'Ordinateur')
        self.assertEqual(kpis['quantite_totale'], 13)
        self.assertEqual(len(kpis['ca_par_jour']), 3)
        self.assertEqual(len(kpis['ca_par_mois']), 2)
        self.assertEqual(len(kpis['ca_par_annee']), 1)
        self.assertEqual(kpis['evolution_volume'], -91.67)

    def test_filtre_client_et_produit(self):
        kpis = calculer_kpis(clients=['Client A'], produits=['Ordinateur'])

        self.assertEqual(kpis['ca_total'], 3200)
        self.assertEqual(kpis['nombre_ventes'], 2)
        self.assertEqual(kpis['quantite_totale'], 3)

    def test_dashboard_affiche_filtres_et_graphiques_consolides(self):
        response = self.client.get(reverse('dashboard'), {'clients': ['Client A'], 'produits': ['Ordinateur']})

        self.assertContains(response, 'Filtres du dashboard')
        self.assertContains(response, "Évolution du chiffre d'affaires et prévisions")
        self.assertContains(response, 'Contribution des produits au chiffre d’affaires')
        self.assertContains(response, 'Volume vendu')
        self.assertContains(response, 'Régions')
        self.assertContains(response, 'caDataLabels')
        self.assertContains(response, 'forecastBoundary')
        self.assertContains(response, 'CA prévisionnel')
        self.assertContains(response, 'Pourquoi cette prévision ?')
        self.assertContains(response, 'Intervalle à 95 %')
        self.assertContains(response, 'Données analysées')
        self.assertNotContains(response, 'Données et recommandations justifiées')
        self.assertContains(response, 'Lignes analysées')
        self.assertContains(response, 'Casablanca')
        self.assertNotContains(response, 'Rabat')
        self.assertNotContains(response, '<h3>CA par mois</h3>', html=True)

    def test_filtre_rapide_ignore_les_selecteurs_vides(self):
        response = self.client.get(
            reverse('dashboard'),
            {'produits': 'Ordinateur', 'clients': '', 'date_debut': '', 'date_fin': ''},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['produits_selectionnes'], ['Ordinateur'])
        self.assertEqual(response.context['clients_selectionnes'], [])
        self.assertEqual(response.context['kpis']['ca_total'], 3200)

    def test_prediction_utilise_mmp_si_historique_inferieur_a_six_mois(self):
        prediction = predire_ca_pour_ventes(Vente.objects.all(), nb_mois=2)

        self.assertEqual(prediction['methode'], 'mmp')
        self.assertEqual(prediction['profondeur_historique'], 2)
        self.assertEqual(prediction['fiabilite'], 'basse')
        self.assertEqual(prediction['mois'], ['03/2026', '04/2026'])
        self.assertEqual(prediction['valeurs'], [1800.0, 1820.0])
        self.assertEqual(len(prediction['intervalle_confiance']), 2)
        self.assertEqual(prediction['niveau_confiance'], 95)
        self.assertIsNone(prediction['validation_retrospective'])

    def test_prediction_est_mise_en_cache_et_invalidee_par_les_donnees(self):
        cache.clear()
        resultat = {
            'methode': 'mmp',
            'mois': ['03/2026'],
            'valeurs': [100.0],
            'fiabilite': 'basse',
            'profondeur_historique': 2,
            'intervalle_confiance': None,
        }

        with patch('sales.prediction._calculer_prevision', return_value=resultat) as calcul:
            predire_ca_pour_ventes(Vente.objects.all(), nb_mois=1)
            predire_ca_pour_ventes(Vente.objects.all(), nb_mois=1)
            self.assertEqual(calcul.call_count, 1)

            Vente.objects.create(
                date=date(2026, 2, 12),
                client='Client C',
                produit='Clavier',
                quantite=1,
                prix_unitaire=100,
                cout_unitaire=50,
                region='Fès',
            )
            predire_ca_pour_ventes(Vente.objects.all(), nb_mois=1)

        self.assertEqual(calcul.call_count, 2)

    def test_export_dashboard_pdf_reprend_kpis_et_graphiques(self):
        response = self.client.get(
            reverse('dashboard_pdf'),
            {'clients': ['Client A'], 'produits': ['Ordinateur']},
        )

        if response.status_code in {500, 503} and b'WeasyPrint requiert' in response.content:
            self.skipTest('Les bibliotheques systeme GTK/Pango de WeasyPrint ne sont pas installees.')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('dashboard-salesdecision.pdf', response['Content-Disposition'])

        lecteur = PdfReader(BytesIO(response.content))
        self.assertEqual(len(lecteur.pages), 1)
        texte = ''.join(page.extract_text() or '' for page in lecteur.pages)
        self.assertRegex(texte, r'3\s*200[,.]00\s*DH')
        self.assertIn('2', texte)
        self.assertIn('Performance commerciale', texte)
        self.assertIn('Répartition commerciale', texte)
        self.assertIn('Rapport préparé à partir des filtres actifs du tableau de bord', texte)

    def test_export_dashboard_pdf_sans_filtre(self):
        response = self.client.get(reverse('dashboard_pdf'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_export_dashboard_pdf_utilise_la_repartition_selectionnee(self):
        response = self.client.get(reverse('dashboard_pdf'), {'repartition': 'client', 'granularite': 'annee'})

        self.assertEqual(response.status_code, 200)
        lecteur = PdfReader(BytesIO(response.content))
        texte = ''.join(page.extract_text() or '' for page in lecteur.pages)
        self.assertIn('Performance commerciale', texte)
        self.assertIn('Clients', texte)


class AuthenticationAndRolesTests(TestCase):
    def test_une_vue_sensible_redirige_vers_la_connexion(self):
        response = self.client.get(reverse('dashboard'))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_connexion_conserve_la_page_demandee(self):
        user = User.objects.create_user(username='metier', password='mot-de-passe-fort')

        response = self.client.post(
            reverse('login'),
            {'username': user.username, 'password': 'mot-de-passe-fort', 'next': reverse('liste_ventes')},
        )

        self.assertRedirects(response, reverse('liste_ventes'))

    def test_seul_le_groupe_decideur_recoit_la_permission_de_seuils(self):
        decideur = Group.objects.get(name='Décideur')
        utilisateur_metier = Group.objects.get(name='Utilisateur de métiers')
        permission = Permission.objects.get(codename='configure_thresholds', content_type__app_label='sales')
        user_decideur = User.objects.create_user(username='decideur', password='mot-de-passe-fort')
        user_metier = User.objects.create_user(username='utilisateur-metier', password='mot-de-passe-fort')
        user_decideur.groups.add(decideur)
        user_metier.groups.add(utilisateur_metier)

        self.assertTrue(decideur.permissions.filter(pk=permission.pk).exists())
        self.assertFalse(utilisateur_metier.permissions.filter(pk=permission.pk).exists())
        self.assertTrue(user_decideur.has_perm('sales.configure_thresholds'))
        self.assertFalse(user_metier.has_perm('sales.configure_thresholds'))

    def test_utilisateur_metier_recoit_la_permission_import(self):
        utilisateur_metier = Group.objects.get(name='Utilisateur de métiers')
        permission = Permission.objects.get(codename='import_sales', content_type__app_label='sales')
        user_metier = User.objects.create_user(username='importateur', password='mot-de-passe-fort')
        user_metier.groups.add(utilisateur_metier)

        self.assertTrue(utilisateur_metier.permissions.filter(pk=permission.pk).exists())
        self.assertTrue(user_metier.has_perm('sales.import_sales'))


class AlertesTests(TestCase):
    def setUp(self):
        initialiser_seuils_par_defaut()

    def test_initialisation_repetee_necrit_pas_en_base(self):
        with self.assertNumQueries(1):
            initialiser_seuils_par_defaut()

    def test_alerte_rouge_est_declenchee_par_une_baisse_par_rapport_a_l_historique(self):
        seuil = SeuilAlerte.objects.get(code_alerte='baisse_ca')
        seuil.seuil_orange = -5
        seuil.seuil_rouge = -15
        seuil.save()

        alertes = construire_alertes_dashboard(
            {
                'ca_par_mois': [
                    {'ca': 5000}, {'ca': 5000}, {'ca': 5000}, {'ca': 4000},
                ],
            },
            {'valeurs': []},
        )

        self.assertTrue(any(alerte['code_alerte'] == 'baisse_ca' and alerte['niveau'] == 'rouge' for alerte in alertes))

    def test_utilisateur_sans_permission_ne_peut_pas_configurer_les_alertes(self):
        user = User.objects.create_user(username='commercial', password='mot-de-passe-fort')
        self.client.force_login(user)

        response = self.client.get(reverse('configurer_alertes'))

        self.assertEqual(response.status_code, 403)

class UserManagementTests(TestCase):
    def setUp(self):
        self.administrator = User.objects.create_user(
            username='admin', password='mot-de-passe-fort', is_staff=True,
        )
        self.administrator.groups.add(Group.objects.get(name='Décideur'))
        self.role = Group.objects.get(name='Utilisateur de métiers')

    def login_administrator(self):
        self.client.force_login(self.administrator)

    def test_administrateur_peut_creer_un_utilisateur_et_lui_attribuer_un_role(self):
        self.login_administrator()

        response = self.client.post(reverse('create_user'), {
            'first_name': 'Nadia',
            'last_name': 'Amrani',
            'email': 'nadia@example.com',
            'group': self.role.pk,
        })

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email='nadia@example.com')
        self.assertRegex(user.username, r'^n\.amrani-[a-z0-9]{5}$')
        self.assertEqual(user.first_name, 'Nadia')
        self.assertEqual(user.email, 'nadia@example.com')
        self.assertTrue(user.groups.filter(pk=self.role.pk).exists())
        self.assertEqual(user.provisioning.created_by, self.administrator)
        self.assertTrue(user.provisioning.must_change_password)
        self.assertContains(response, user.username)
        self.assertContains(response, 'affichage unique')
        self.assertEqual(response['Cache-Control'], 'no-store, no-cache, must-revalidate, private')

        # Seul le hash est persistant; le secret en clair n'est dans aucun modèle.
        temporary_password = response.context['credentials'].temporary_password
        self.assertTrue(user.check_password(temporary_password))
        self.assertTrue(user.password.startswith('argon2$'))
        self.assertNotIn(temporary_password, repr(user.provisioning.__dict__))

    def test_page_racine_redirige_vers_le_tableau_de_bord(self):
        response = self.client.get('/')

        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)

    def test_premiere_connexion_impose_le_changement_du_mot_de_passe(self):
        self.login_administrator()
        response = self.client.post(reverse('create_user'), {
            'first_name': 'Nadia',
            'last_name': 'Amrani',
            'email': 'nadia@example.com',
            'group': self.role.pk,
        })
        credentials = response.context['credentials']
        self.client.logout()

        self.assertTrue(self.client.login(
            username=credentials.username,
            password=credentials.temporary_password,
        ))
        dashboard = self.client.get(reverse('dashboard'))
        self.assertRedirects(dashboard, reverse('provisioning_password_change'))
        change_page = self.client.get(reverse('provisioning_password_change'))
        self.assertTemplateUsed(change_page, 'sales/password_change_form.html')
        self.assertContains(change_page, 'Sécurisez votre compte')

        changed = self.client.post(reverse('provisioning_password_change'), {
            'old_password': credentials.temporary_password,
            'new_password1': 'Une-longue-phrase-secrete-2026!',
            'new_password2': 'Une-longue-phrase-secrete-2026!',
        })
        self.assertRedirects(changed, reverse('provisioning_password_change_done'))
        user = User.objects.get(username=credentials.username)
        user.provisioning.refresh_from_db()
        self.assertFalse(user.provisioning.must_change_password)
        self.assertTrue(user.check_password('Une-longue-phrase-secrete-2026!'))

    def test_administrateur_peut_creer_un_utilisateur_sans_email(self):
        self.login_administrator()

        response = self.client.post(reverse('create_user'), {
            'first_name': 'Salma',
            'last_name': 'Benali',
            'email': '',
            'group': self.role.pk,
        })

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(first_name='Salma', last_name='Benali')
        self.assertEqual(user.email, '')
        self.assertIsNotNone(response.context['credentials'])

    def test_utilisateur_non_administrateur_ne_peut_pas_acceder_a_la_page(self):
        user = User.objects.create_user(username='analyste', password='mot-de-passe-fort')
        user.groups.add(Group.objects.get(name='Décideur'))
        self.client.force_login(user)

        dashboard = self.client.get(reverse('dashboard'))
        response = self.client.get(reverse('create_user'))

        self.assertContains(dashboard, 'Décideur')
        self.assertNotContains(dashboard, 'Créer un utilisateur')
        self.assertNotContains(dashboard, '>Utilisateurs</a>')
        self.assertEqual(response.status_code, 403)

    def test_page_securite_est_reservee_a_l_administrateur(self):
        metier = User.objects.create_user(username='securite-metier', password='mot-de-passe-fort')
        metier.groups.add(self.role)
        self.client.force_login(metier)
        self.assertEqual(self.client.get(reverse('security_users')).status_code, 403)

        self.client.force_login(self.administrator)
        response = self.client.get(reverse('security_users'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sécurité des comptes')
        self.assertContains(response, self.administrator.username)
        self.assertNotContains(response, 'mot-de-passe-fort')

    def test_administrateur_peut_supprimer_un_compte_metier(self):
        target = User.objects.create_user(username='compte-a-supprimer', password='mot-de-passe-fort')
        target.groups.add(self.role)
        self.login_administrator()

        response = self.client.post(reverse('delete_user_account', args=[target.pk]), follow=True)

        self.assertRedirects(response, reverse('security_users'))
        self.assertFalse(User.objects.filter(pk=target.pk).exists())
        self.assertContains(response, 'a été supprimé')

    def test_administrateur_ne_peut_pas_supprimer_son_propre_compte(self):
        self.login_administrator()

        response = self.client.post(
            reverse('delete_user_account', args=[self.administrator.pk]),
            follow=True,
        )

        self.assertTrue(User.objects.filter(pk=self.administrator.pk).exists())
        self.assertContains(response, 'propre compte')

    def test_utilisateur_metier_peut_importer_sans_pouvoir_supprimer_les_ventes(self):
        user = User.objects.create_user(username='metier', password='mot-de-passe-fort')
        user.groups.add(self.role)
        self.client.force_login(user)

        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('liste_ventes')).status_code, 200)
        self.assertEqual(self.client.get(reverse('import_ventes')).status_code, 200)
        self.assertContains(self.client.get(reverse('dashboard')), 'Importer')
        self.assertEqual(self.client.post(reverse('supprimer_ventes')).status_code, 403)

    def test_administrateur_accede_directement_au_tableau_de_bord(self):
        response = self.client.post(reverse('login'), {
            'username': self.administrator.username,
            'password': 'mot-de-passe-fort',
        })

        self.assertRedirects(response, reverse('dashboard'))

    def test_connexion_est_verrouillee_apres_cinq_echecs(self):
        user = User.objects.create_user(username='verrouillage', password='mot-de-passe-fort')
        for _ in range(5):
            self.client.post(reverse('login'), {
                'username': user.username,
                'password': 'incorrect',
            })

        response = self.client.post(reverse('login'), {
            'username': user.username,
            'password': 'mot-de-passe-fort',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Trop de tentatives')
        self.assertNotIn('_auth_user_id', self.client.session)
