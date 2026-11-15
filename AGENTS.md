# AKO-FX agent entry point

Read README.md, docs/ARCHITECTURE.md, docs/API.md and docs/ACCEPTANCE.md before changes. Verify owner/repository, branch and actual head. Repository: sina1991/AKO-FX. Never confuse this project with the reference 30nA-Hybrid-architecture repository.

## Invariants

- DEMO ONLY. No real payments, exchange/broker execution, wallet signing, credentials for live trading, or LIVE switch.
- All HTTP and CLI operations use application.dispatch; never bypass authorization in an adapter.
- Money is integer cents; validate through store.money. Each transfer creates balanced immutable ledger entries in the same BEGIN IMMEDIATE transaction as cached balances and domain changes.
- POST mutations require Idempotency-Key bound to user, operation and canonical body. Retry matches return the original result; conflicting reuse must fail.
- All account and position actions verify ownership. Admin promotion is local management only.
- No default credentials. No secrets in source, logging, issue text or tests.
- Preserve independent role routing and the single-host shared SQLite constraint. Do not describe this release as isolated databases or distributed microservices.
- Versioned Prop accounts use prop_contracts snapshots and two reviewed phases before funded-demo. Read docs/PROP_RULES.md and contracts/prop-rules-v1.json. Never rewrite rules for existing legacy accounts or bypass pending-request locks, recorded breaches or review checks.
- Prop capital cannot be withdrawn to the wallet. Final passed/failed statuses are terminal. Failed positions settle atomically when scenarios trigger loss thresholds.

## Map

- ako_fx/store.py: schema, transaction, ledger, audit and idempotency.
- ako_fx/services/: identity, wallet, broker and prop domain behavior; prop_rules.py holds the dated source catalogue.
- ako_fx/application.py: authorization-aware operations and role routing.
- ako_fx/server.py: bounded request body, HTTP handling, static UI and gateway.
- ako_fx/cli.py: API client; ako_fx/manage.py: local bootstrap and backup.
- ako_fx/services/dashboard.py: owner-only revisioned layout/note/template settings; strictly visual, no account deletion.
- ako_fx/web/workspace.js and workspace.css: context menus and persistent slots. Preserve native input menus, role filtering, focus/keyboard/mobile behavior and logout cleanup. Duplicate is a read-only mirror; never duplicate a financial account or submit an action just by opening a menu.
- tests/test_dashboard.py and tests/browser_workspace.py cover layout isolation and financial invariants.
- ako_fx/web/: Persian UI; compose.yaml and deploy/: single-VPS deployment.
- install.sh and scripts/installer.py: root-only Ubuntu 24.04 bootstrap, Docker endpoint/volume adoption, verified TLS and owned Nginx files. Read docs/INSTALLER.md; never stop/reconfigure another daemon/site. Preserve existing admin and backup before update.
- tests/test_installer.py: preflight, adoption, TLS validation and failure recovery. scripts/installer_smoke.sh: dedicated CI host only, never run on a user VPS.
- tests/test_acceptance.py: deterministic API, integrity, concurrency and multi-service checks.
- tests/browser_acceptance.py: optional real Chromium journey.

Run relevant tests, record exact results and limitations in docs/ACCEPTANCE.md, and update API/docs when behavior changes. Do not claim Docker, CI or remote deployment passed without observed evidence. Do not issue credentials in final reports.
