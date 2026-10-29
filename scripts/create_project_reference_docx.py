from datetime import date
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "SalesDecision_AI_Project_Reference.docx"
TODAY = date.today().strftime("%d %B %Y")

def x(text):
    return escape(str(text), {'\n': '&#10;'})

def run(text, bold=False, italic=False, size=None, color=None):
    props = ''
    if bold: props += '<w:b/>'
    if italic: props += '<w:i/>'
    if size: props += f'<w:sz w:val="{size}"/>'
    if color: props += f'<w:color w:val="{color}"/>'
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{x(text)}</w:t></w:r>'

def para(text='', style=None, bold=False, italic=False, size=None, color=None, before=None, after=None):
    ppr = f'<w:pStyle w:val="{style}"/>' if style else ''
    if before is not None or after is not None:
        ppr += '<w:spacing' + (f' w:before="{before}"' if before is not None else '') + (f' w:after="{after}"' if after is not None else '') + '/>'
    return f'<w:p><w:pPr>{ppr}</w:pPr>{run(text, bold, italic, size, color)}</w:p>'

def bullet(text, level=0):
    return f'<w:p><w:pPr><w:pStyle w:val="ListBullet"/><w:ind w:left="{720 + level*360}" w:hanging="360"/></w:pPr>{run("• ")}{run(text)}</w:p>'

def page_break():
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'

def cell(text, header=False, width=None):
    width_xml = f'<w:tcW w:w="{width}" w:type="dxa"/>' if width else ''
    shading = '<w:shd w:fill="17365D"/>' if header else ''
    content = para(text, bold=header, color='FFFFFF' if header else None, after=0)
    return f'<w:tc><w:tcPr>{width_xml}{shading}<w:tcMar><w:top w:w="90" w:type="dxa"/><w:left w:w="110" w:type="dxa"/><w:bottom w:w="90" w:type="dxa"/><w:right w:w="110" w:type="dxa"/></w:tcMar></w:tcPr>{content}</w:tc>'

def table(headers, rows, widths=None):
    grid = ''.join(f'<w:gridCol w:w="{w}"/>' for w in (widths or [9000//len(headers)]*len(headers)))
    out = f'<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblLayout w:type="fixed"/><w:tblBorders><w:top w:val="single" w:sz="4" w:color="B7C9DE"/><w:left w:val="single" w:sz="4" w:color="B7C9DE"/><w:bottom w:val="single" w:sz="4" w:color="B7C9DE"/><w:right w:val="single" w:sz="4" w:color="B7C9DE"/><w:insideH w:val="single" w:sz="4" w:color="D9E2F3"/><w:insideV w:val="single" w:sz="4" w:color="D9E2F3"/></w:tblBorders></w:tblPr><w:tblGrid>{grid}</w:tblGrid>'
    out += '<w:tr>' + ''.join(cell(h, True, (widths or [None]*len(headers))[i]) for i,h in enumerate(headers)) + '</w:tr>'
    for row in rows:
        out += '<w:tr>' + ''.join(cell(v, False, (widths or [None]*len(headers))[i]) for i,v in enumerate(row)) + '</w:tr>'
    return out + '</w:tbl>'

parts = []
parts += [para('PROJECT REFERENCE DOCUMENT', size=24, bold=True, color='17365D', after=120),
          para('SalesDecision AI / DecisionIQ', size=48, bold=True, color='17365D', after=180),
          para('Sales intelligence, decision support and commercial performance platform', size=26, color='4F81BD', after=440),
          para('Purpose: complete project reference for conversion into a PowerPoint presentation', italic=True, size=22, after=360),
          para(f'Prepared from the repository evidence available on {TODAY}.', size=20, after=120),
          para('Status note: the repository documents implemented functionality. No approved project charter, named sponsor, dates, headcount, or budget were provided; those items are explicitly labelled as planning assumptions or decisions required.', size=20, color='7F6000')]
parts += [page_break(), para('Document control', 'Heading1')]
parts += [table(['Item', 'Value'], [
    ('Project', 'SalesDecision AI / Django project package: DecisionIQ'),
    ('Document purpose', 'Complete reference document and slide-ready source material'),
    ('Evidence reviewed', 'Application code, configuration, recommendation design, assistant audit, deployment guide, QA report, tests and sample CSV files'),
    ('Language of product', 'French user interface and operational documentation; this reference is written in English for broader stakeholder use'),
    ('Known planning gaps', 'Sponsor, business owner, implementation dates, target data volume, user count, hosting choice, approved budget and procurement terms are not present in the repository'),
])]

parts += [para('1. Executive summary', 'Heading1'),
          para('SalesDecision AI is a web application that turns imported sales records into a controlled commercial decision-support workspace. It centralizes sales data, calculates revenue, cost and margin indicators, highlights alert conditions, produces explainable rule-based recommendations, forecasts revenue, and offers a bounded conversational assistant for interpreting results.'),
          para('The implemented product is intended for commercial decision-makers, business users who load and explore sales data, and administrators who manage users and security. Its core design principle is traceability: calculated facts remain on the server, recommendations include evidence and confidence, and the assistant receives a limited analytical summary rather than raw transaction lines.'),
          table(['Decision value', 'Implemented mechanism', 'Why it matters'], [
              ('Faster diagnosis', 'Dashboard filtered by period, client and product; KPI and drill-down views', 'Reduces manual consolidation before a commercial review'),
              ('Actionable signals', 'Threshold alerts and ranked recommendations with a proposed action', 'Moves discussion from observations to next actions'),
              ('Controlled forecasting', 'ARIMA where history is sufficient; moving-average fallback otherwise', 'Avoids presenting a fragile forecast as certainty'),
              ('Governed access', 'Authentication, roles, permissions, password controls and login throttling', 'Limits access to sales information and administration'),
              ('Assistive analysis', 'Optional Ollama/OpenAI assistant with bounded context and feedback logging', 'Supports questions without giving the model direct database access'),
          ], [2000, 3600, 3400])]

parts += [para('2. Project context, problem, purpose and users', 'Heading1'),
          para('Problem addressed', 'Heading2'),
          para('Commercial teams commonly receive sales data as periodic spreadsheets. Without a shared analytical workflow, comparing periods, identifying concentration or margin risk, checking forecast variance, and documenting follow-up actions are manual, inconsistent and slow. The project addresses this by providing one operational application for import, analysis, alerts, recommendations and controlled interpretation.'),
          para('Purpose', 'Heading2'),
          para('Provide a practical decision-support layer over transactional sales data. The purpose is not to replace commercial judgement; it is to make the facts, exceptions, assumptions and suggested follow-up actions visible and reproducible.'),
          para('Target users and responsibilities', 'Heading2'),
          table(['User group', 'Primary need', 'Relevant capability'], [
              ('Decision-maker', 'Review performance and set operational focus', 'Dashboard, recommendations, forecast, alert-threshold configuration'),
              ('Business user', 'Load and explore sales records', 'CSV/Excel import, sales list, dashboard filtering and analysis'),
              ('Administrator', 'Provision accounts and maintain secure access', 'User creation, role assignment, password lifecycle and security page'),
              ('Technical/operations team', 'Deploy, monitor and restore the system', 'Environment configuration, health endpoint, encrypted backups and production hardening'),
          ], [1800, 3200, 4400]),
          para('Assumption to validate: the repository establishes role mechanisms, but it does not identify the actual organization, business sponsor, data owner, or the number of users who will operate the system.', italic=True, color='7F6000')]

parts += [para('3. Objectives, scope and exclusions', 'Heading1'),
          para('General objective', 'Heading2'),
          para('Enable repeatable, secure and explainable sales-performance decisions from imported transaction data.'),
          para('Specific objectives', 'Heading2')]
for t in ['Import validated CSV, XLSX and XLS sales files within the configured size limit (10 MB by default).', 'Calculate revenue, total cost and margin from quantity, unit price and unit cost.', 'Segment analysis by time period, product, client and region.', 'Surface configurable alerts and deterministic recommendations based on transparent thresholds and evidence.', 'Forecast revenue for a selected horizon, while disclosing low-history or convergence limitations.', 'Allow natural-language questions using only a bounded analytical context and log feedback for quality improvement.', 'Apply authentication, role-based permissions, strong password policy, lockout controls and operational backups.']:
    parts.append(bullet(t))
parts += [para('In scope (repository evidence)', 'Heading2'),
          table(['Area', 'Included capability'], [
              ('Data intake', 'Validation of file type/signature and error handling for CSV, XLSX and XLS; records include date, client, product, quantity, unit price, unit cost and region.'),
              ('Analysis', 'Dashboard, sales list, filtering, KPIs, visualizations, PDF dashboard export, alerts, recommendations and forecast.'),
              ('Recommendation engine', 'Rules for revenue decline/growth, margin risk, product/client/region concentration, quantity anomalies, forecast gaps and insufficient-data states.'),
              ('Assistant', 'Chat endpoints, streaming, history reset, feedback, intent handling and optional Ollama/OpenAI provider.'),
              ('Security/operations', 'Roles, import/configuration permissions, password change flow, throttling, secure production settings, health checks and encrypted backup command.'),
          ], [2400, 6600]),
          para('Out of scope / not evidenced', 'Heading2'),
          table(['Excluded or unconfirmed item', 'Reason / boundary'], [
              ('Automatic causal diagnosis', 'Rules identify signals; documentation explicitly says the system must not claim unproven causality.'),
              ('Machine-learned recommendation prioritization', 'Version 1 uses deterministic rules and weighted scoring; no labeled outcome history is available.'),
              ('Direct ERP/CRM/API integration', 'No connector or integration implementation is present in the reviewed repository.'),
              ('Automated action execution', 'The application recommends actions; no evidence shows it creates campaigns, orders, CRM tasks or approvals.'),
              ('Approved hosting, SLA, RPO/RTO or compliance certification', 'Deployment guidance exists, but contractual operating targets and certifications are not provided.'),
          ], [3300, 5700])]

parts += [para('4. Methodology, key steps and activities', 'Heading1'),
          para('Delivery and operating methodology', 'Heading2'),
          para('The product follows an evidence-first analytical workflow. Sales data is validated before import; the dashboard applies requested filters; calculations and forecasts are produced server-side; the recommendation engine evaluates rules against the same filtered data; results are prioritized and rendered with supporting evidence. The assistant is downstream of this process and interprets a limited analytical dossier rather than querying raw data directly.'),
          table(['Step', 'Activity', 'Control / output'], [
              ('1. Prepare data', 'Prepare CSV/XLS/XLSX with required commercial fields; remove corrupt or unsupported files.', 'Extension/signature checks and file-size limit; functional errors rather than technical traces.'),
              ('2. Import', 'Authorized business user imports sales records.', 'Validated records are stored as Vente data; imports are permission-controlled.'),
              ('3. Filter analysis', 'Select date range, client and/or product in dashboard.', 'A shared filtered query set drives KPI, forecast and recommendation calculations.'),
              ('4. Compute indicators', 'Aggregate revenue, quantity, cost, margin and completeness by time and entity.', 'Reproducible server-side calculations; missing/weak data are surfaced.'),
              ('5. Forecast', 'Use monthly history to project revenue.', 'ARIMA is selected when sufficient history exists; otherwise moving-average fallback and warning.'),
              ('6. Evaluate rules', 'Apply thresholds to changes, risk concentration, margin, anomaly and forecast-gap conditions.', 'Each recommendation contains rule ID, values, comparison period, confidence and suggested action.'),
              ('7. Prioritize and decide', 'Review ranked signals, validate business context, assign human follow-up.', 'Maximum displayed recommendations is configured as 8; system supports decisions, not causal proof.'),
              ('8. Learn and improve', 'Gather user feedback on assistant answers; recalibrate thresholds after business review.', 'Feedback/audit data exist; threshold recalibration is recommended after 3–6 months of use.'),
          ], [1000, 4800, 3200]),
          para('Recommendation logic and explainability', 'Heading2'),
          para('The documented scoring model combines severity (35%), financial impact (25%), duration (15%), data reliability (15%) and analysis confidence (10%) into a 0–100 score. Initial priority bands are low (0–39), medium (40–59), high (60–79) and critical (80–100). Initial thresholds are configuration values, not universally valid business constants: for example, a global revenue decline is triggered at −10%, strong product decline at −20%, low margin at ≤10%, client dependency at ≥35%, and forecast gap at ≥20%.'),
          para('Important limitation: thresholds must be approved and calibrated using the organization’s own commercial history. They should not be treated as final policy solely because they are defaults in the code.', italic=True, color='7F6000')]

parts += [para('5. Deliverables, expected results and success criteria', 'Heading1'),
          table(['Deliverable', 'Description', 'Evidence / acceptance basis'], [
              ('Sales import workflow', 'Controlled import of CSV/Excel sales files.', 'Automated tests cover empty, header-only, oversize and corrupt-file cases.'),
              ('Sales dashboard', 'KPIs, filtered analysis, charts and PDF export.', 'Dashboard and export routes are implemented.'),
              ('Alert configuration', 'Threshold configuration with history of changes.', 'SeuilAlerte and HistoriqueConfigurationAlerte models and configuration view.'),
              ('Recommendation engine', 'Explainable signals with rule IDs, evidence, score, confidence and actions.', 'Documented rule catalogue and automated recommendation tests.'),
              ('Forecasting module', 'Revenue forecast with model fallback and warning states.', 'ARIMA/moving-average logic in prediction module.'),
              ('Commercial assistant', 'Bounded chat, streaming, feedback and learning records.', 'Assistant services, audit and benchmark materials.'),
              ('Security and operations pack', 'Roles, secure configuration, deployment and encrypted-backup guidance.', 'Settings, permissions, deployment guide and backup command.'),
          ], [2400, 4000, 2600]),
          para('Expected results', 'Heading2')]
for t in ['A business user can import valid sales data and obtain a dashboard without manual spreadsheet aggregation.', 'A decision-maker can trace a recommendation back to the values, period and rule that generated it.', 'A forecast warning is displayed where history is too short or ARIMA cannot converge.', 'A user can ask the assistant about the current analysis without transmitting raw sales rows to the language model.', 'Unauthorized users cannot perform privileged threshold or import activities assigned to other roles.']:
    parts.append(bullet(t))
parts += [para('Success criteria', 'Heading2'),
          table(['Criterion', 'Measure / decision rule', 'Status from repository'], [
              ('Functional correctness', 'Automated test suite passes; expected recommendation rules trigger without duplicates or contradictory signals.', 'Tests are present; a fresh execution result was not supplied in the project request.'),
              ('Calculation integrity', 'Revenue and margin recomputation from Vente records agrees to the centime.', 'Defined in recommendation acceptance criteria.'),
              ('Data-quality guardrail', 'No substantive recommendation is shown when fewer than 5 rows, fewer than 2 periods, or completeness is below 70%.', 'Documented as REC_DONNEES_INSUFFISANTES behavior.'),
              ('Security baseline', 'Production uses DEBUG=False, secrets outside repository, HTTPS proxy configuration and protected cookies.', 'Deployment/settings guidance exists; production configuration must be verified.'),
              ('Business adoption', 'Named users complete an agreed acceptance scenario and confirm usefulness of the top signals.', 'Target users, scenario and target score are not yet defined.'),
          ], [2500, 4200, 2300])]

parts += [para('6. Timeline and milestones', 'Heading1'),
          para('The repository does not contain approved dates, a baseline schedule or delivery history. The following is a proposed 12-week deployment roadmap, anchored to T0 = project authorization. It must be replaced with owner-approved dates before execution.', italic=True, color='7F6000'),
          table(['Milestone', 'Indicative timing', 'Key activities', 'Exit criterion'], [
              ('M0: Mobilize', 'Week 1', 'Name sponsor, product owner, data owner; confirm target organization and decision use cases.', 'Signed scope, roles and data access decision.'),
              ('M1: Data readiness', 'Weeks 2–3', 'Profile source files, map fields, clean sample data, define quality rules and retention.', 'Accepted data dictionary and test import files.'),
              ('M2: Environment readiness', 'Weeks 3–4', 'Select hosting/database, configure secrets, TLS, backup location and monitoring.', 'Secure non-production environment passes deployment checklist.'),
              ('M3: Business calibration', 'Weeks 4–6', 'Validate thresholds, forecast horizon, dashboard filters and alert meanings with stakeholders.', 'Approved threshold register and acceptance scenarios.'),
              ('M4: UAT', 'Weeks 7–8', 'Execute functional, security and usability tests with representative users.', 'UAT defects triaged; acceptance decision recorded.'),
              ('M5: Pilot go-live', 'Weeks 9–10', 'Load pilot data, train users, monitor use and assist decisions.', 'Pilot KPIs and incident log reviewed.'),
              ('M6: Stabilize and scale', 'Weeks 11–12', 'Review feedback, tune thresholds, validate restore, decide production expansion.', 'Go/no-go for wider rollout and ongoing operating model.'),
          ], [1800, 1400, 3600, 3200])]

parts += [para('7. Resources and budget', 'Heading1'),
          para('Human resources (proposed minimum operating model)', 'Heading2'),
          table(['Role', 'Core accountability', 'Planning effort'], [
              ('Executive sponsor', 'Business outcomes, funding and escalation decisions.', '0.05–0.10 FTE during rollout'),
              ('Product owner / sales lead', 'Prioritize use cases, approve rules and accept outputs.', '0.20–0.40 FTE'),
              ('Data owner / analyst', 'Source quality, field mapping, reconciliation and data stewardship.', '0.30–0.60 FTE initially; then ongoing part-time'),
              ('Django engineer', 'Configuration, fixes, deployment support and test automation.', '0.50–1.00 FTE during rollout'),
              ('DevOps / security engineer', 'Hosting, secrets, TLS, monitoring, backup/restore and access controls.', '0.15–0.35 FTE during rollout'),
              ('UAT representatives', 'Validate real business scenarios and training material.', '2–4 users, scheduled workshops'),
          ], [2400, 4600, 2200]),
          para('Technical resources', 'Heading2'),
          table(['Component', 'Requirement'], [
              ('Application stack', 'Python, Django 6.0, pandas, statsmodels, pydantic, cryptography and WeasyPrint; optional OpenAI package.'),
              ('Database', 'MySQL is the configured default for production; SQLite database exists locally in the repository and is not a production decision.'),
              ('Hosting/security', 'HTTPS reverse proxy, secret manager, environment variables, health monitoring and static-file delivery.'),
              ('Backup', 'Encrypted backup key, retention policy (guide suggests 14 days), external immutable storage and scheduled restore tests.'),
              ('Assistant runtime', 'Default local Ollama service with qwen3:1.7b; OpenAI is an optional external provider with a server-side API key.'),
          ], [2500, 6500]),
          para('Budget', 'Heading2'),
          para('No approved budget, pricing assumptions, vendor quote, user count, hosting tier, support model or LLM usage estimate exists in the reviewed materials. Therefore, a truthful fixed budget cannot be stated. Obtain quotes and build the budget from the following cost categories before approval:'),
          table(['Cost category', 'Basis required for estimate', 'Decision needed'], [
              ('Implementation labor', 'Role rates × approved effort / duration.', 'Internal capacity versus external services.'),
              ('Hosting and database', 'Region, availability, storage, backup volume and network needs.', 'Cloud/on-premises provider and service tier.'),
              ('Security and operations', 'Monitoring, secret manager, certificate, backup/restore and support coverage.', 'Required SLA, RPO and RTO.'),
              ('Assistant inference', 'Local hardware/Ollama operations or external API token volume and model choice.', 'Privacy posture and expected question volume.'),
              ('Training and change', 'Number of users, workshops, documentation and pilot support.', 'Rollout population and training format.'),
          ], [2400, 4000, 2600])]

parts += [para('8. Risks, challenges and mitigation', 'Heading1'),
          table(['Risk / challenge', 'Impact', 'Mitigation / owner'], [
              ('Incomplete or inconsistent sales data', 'Misleading KPIs and unreliable recommendations.', 'Use import validation; profile data before pilot; enforce a data dictionary; retain insufficient-data state. Owner: Data owner.'),
              ('Uncalibrated business thresholds', 'Alert fatigue or missed material risks.', 'Run 3–6 months of review; compare signals to outcomes; approve threshold changes with audit history. Owner: Product owner.'),
              ('Short or unstable history', 'Forecast quality is weak; ARIMA may not converge.', 'Use documented moving-average fallback and warning; require human review before committing resources. Owner: Sales lead.'),
              ('Over-trust in AI responses', 'Users may treat interpretation as fact or causal proof.', 'Keep factual constraints in prompts; display missing-data caveats; train users; require decision accountability. Owner: Product owner.'),
              ('Sensitive-data exposure via external LLM', 'Privacy/compliance concern.', 'Prefer local Ollama where required; send only bounded aggregates; validate policy and vendor terms before enabling OpenAI. Owner: Security lead.'),
              ('Unauthorized access or account compromise', 'Exposure or unauthorized change to sales/security settings.', 'Role permissions, Argon2 hashing, 15-character password minimum, CSRF protections, secure cookies and login throttling. Owner: Administrator.'),
              ('Backup cannot be restored', 'Operational outage or data loss.', 'Encrypt backups; store externally; test restoration regularly in isolated environment. Owner: Operations.'),
              ('Scope expansion into integrations/automation', 'Schedule and cost growth.', 'Keep ERP/CRM integration and automatic action execution as separate approved work packages. Owner: Sponsor.'),
          ], [2400, 2800, 4200])]

parts += [para('9. Conclusion and recommended next steps', 'Heading1'),
          para('SalesDecision AI has a substantive implemented foundation for sales-data analysis and explainable decision support. Its strongest qualities are traceable calculations, deterministic recommendation logic, data-quality guardrails, controlled assistant context, and security/operations features. The remaining work to achieve a dependable rollout is chiefly organizational: establish ownership, validate real data, calibrate business thresholds, select production operations, and demonstrate user value in a pilot.'),
          para('Recommended next steps', 'Heading2')]
for t in ['Appoint the executive sponsor, product owner, data owner, technical owner and security owner; publish their decision rights.', 'Confirm the target sales process, source-system fields, data-retention rules, user population and privacy requirements.', 'Run a data-profiling workshop using representative historical sales files; reconcile revenue and margin calculations with the source of record.', 'Approve a threshold register and forecast-use policy; document which signals require action and who owns follow-up.', 'Select production hosting, MySQL configuration, secret manager, backup target, monitoring, RPO/RTO and support coverage.', 'Execute the proposed UAT scenarios, including corrupt files, incomplete history, role permissions, recommendation reproducibility and restore testing.', 'Pilot with a small commercial team for 3–6 months; measure adoption, signal usefulness, forecast reliability and assistant feedback before broader rollout.', 'Convert this document into a presentation: one slide per numbered section, using the tables as slide content and the timeline/risk table as visual anchors.']:
    parts.append(bullet(t))

parts += [para('Appendix A. Slide conversion map', 'Heading1'),
          table(['Suggested slide', 'Source section', 'Core message'], [
              ('1. Title', 'Cover', 'SalesDecision AI: governed commercial decision support'),
              ('2. Executive summary', 'Section 1', 'What the platform does and why it matters'),
              ('3. Problem and users', 'Section 2', 'Manual sales analysis problem and target roles'),
              ('4. Objectives and scope', 'Section 3', 'Commitments, boundaries and known exclusions'),
              ('5. How it works', 'Section 4', 'Import → analysis → forecast/rules → decision'),
              ('6. Deliverables and outcomes', 'Section 5', 'What is delivered and how success is measured'),
              ('7. Roadmap', 'Section 6', '12-week proposed rollout from T0'),
              ('8. Resources and budget', 'Section 7', 'Operating model; budget inputs still requiring approval'),
              ('9. Risks and controls', 'Section 8', 'Key risks and mitigation ownership'),
              ('10. Decision and next steps', 'Section 9', 'Governance and pilot actions required'),
          ], [2200, 2200, 4800]),
          para('Appendix B. Source traceability', 'Heading1'),
          para('Primary project materials reviewed: RECOMMANDATIONS.md (functional rules and acceptance criteria); ASSISTANT_AUDIT.md (assistant architecture and safeguards); DEPLOYMENT.md (production deployment and backup guidance); BUG_REPORT.md (QA position); sales/models.py, views.py, prediction.py, recommandations.py, permissions.py, upload_validation.py and tests; DecisionIQ/settings.py; requirements.txt. This document deliberately distinguishes repository evidence from proposed project-planning assumptions.')]

document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + \
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + ''.join(parts) + \
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr></w:body></w:document>'

styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos"/><w:sz w:val="21"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="340" w:after="140"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:color w:val="17365D"/><w:sz w:val="32"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="220" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:color w:val="4F81BD"/><w:sz w:val="25"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/></w:style></w:styles>'''
content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>'''
rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>'''
doc_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''
core = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>SalesDecision AI Project Reference</dc:title><dc:creator>Codex</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">{date.today().isoformat()}T00:00:00Z</dcterms:created></cp:coreProperties>'''
app = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Microsoft Office Word</Application></Properties>'''

with ZipFile(OUT, 'w', ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml', content_types)
    z.writestr('_rels/.rels', rels)
    z.writestr('word/document.xml', document)
    z.writestr('word/styles.xml', styles)
    z.writestr('word/_rels/document.xml.rels', doc_rels)
    z.writestr('docProps/core.xml', core)
    z.writestr('docProps/app.xml', app)
print(OUT)
