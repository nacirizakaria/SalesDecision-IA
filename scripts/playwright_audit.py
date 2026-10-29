import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get('AUDIT_BASE_URL', 'http://127.0.0.1:8001')
ADMIN_USERNAME = os.environ['AUDIT_ADMIN_USERNAME']
ADMIN_PASSWORD = os.environ['AUDIT_ADMIN_PASSWORD']
NEW_PASSWORD = os.environ['AUDIT_NEW_PASSWORD']
ARTIFACTS = Path('artifacts/playwright')
ARTIFACTS.mkdir(parents=True, exist_ok=True)


def login(page, username, password):
    page.goto(f'{BASE_URL}/accounts/login/', wait_until='networkidle')
    page.locator('#id_username').fill(username)
    page.locator('#id_password').fill(password)
    page.get_by_role('button', name='Se connecter').click()
    page.wait_for_load_state('networkidle')


def main():
    report = {'console_errors': [], 'page_errors': [], 'http_errors': []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('console', lambda message: (
            report['console_errors'].append(message.text) if message.type == 'error' else None
        ))
        page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
        page.on('response', lambda response: (
            report['http_errors'].append({'status': response.status, 'url': response.url})
            if response.status >= 400 else None
        ))

        login(page, ADMIN_USERNAME, ADMIN_PASSWORD)
        report['admin_landing_url'] = page.url
        page.screenshot(path=ARTIFACTS / '01-dashboard-admin.png', full_page=True)

        chart_metrics = {}
        chart_tabs = {
            'breakdownChart': 'Produits',
            'clientChart': 'Clients',
            'regionChart': 'Régions',
        }
        for chart_id, tab_name in chart_tabs.items():
            page.get_by_role('tab', name=tab_name).click()
            chart = page.locator(f'#{chart_id}')
            if chart.count():
                chart_metrics[chart_id] = chart.bounding_box()
        page.get_by_role('tab', name='Produits').click()
        report['chart_metrics'] = chart_metrics
        report['horizontal_overflow'] = page.evaluate(
            'document.documentElement.scrollWidth > document.documentElement.clientWidth'
        )

        page.goto(f'{BASE_URL}/sales/users/create/', wait_until='networkidle')
        page.locator('#id_first_name').fill('Audit')
        page.locator('#id_last_name').fill('Browser')
        page.locator('#id_email').fill('')
        page.locator('#id_group').select_option(label='Utilisateur de métiers')
        page.get_by_role('button', name="Créer l'utilisateur et générer ses accès").click()
        page.wait_for_load_state('networkidle')
        credentials = page.locator('.credentials code')
        created_username = credentials.nth(0).inner_text().strip()
        temporary_password = credentials.nth(1).inner_text().strip()
        report['created_username'] = created_username
        report['one_time_credentials_visible'] = credentials.count() == 2
        page.screenshot(path=ARTIFACTS / '02-creation-utilisateur.png', full_page=True)

        page.locator('form.nav-logout').get_by_role('button', name='Se déconnecter').click()
        page.wait_for_load_state('networkidle')
        login(page, created_username, temporary_password)
        report['first_login_url'] = page.url
        report['custom_password_page'] = page.get_by_text('Choisissez votre mot de passe').count() == 1
        page.screenshot(path=ARTIFACTS / '03-changement-mot-de-passe.png', full_page=True)

        page.locator('#id_old_password').fill(temporary_password)
        page.locator('#id_new_password1').fill(NEW_PASSWORD)
        page.locator('#id_new_password2').fill(NEW_PASSWORD)
        page.get_by_role('button', name='Enregistrer le nouveau mot de passe').click()
        page.wait_for_load_state('networkidle')
        report['password_change_url'] = page.url

        page.get_by_role('link', name='Accéder au tableau de bord').click()
        page.wait_for_load_state('networkidle')
        report['activated_dashboard_url'] = page.url
        report['business_user_sees_users_menu'] = page.get_by_role('link', name='Utilisateurs').count() > 0
        page.screenshot(path=ARTIFACTS / '04-dashboard-utilisateur.png', full_page=True)
        browser.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
