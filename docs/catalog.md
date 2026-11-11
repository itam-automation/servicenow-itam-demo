# ITAM Toolkit 0.1.0: catalog

> **Kurzfassung:** Scoped App «ITAM Toolkit» (Scope `x_371499_itamkit`) für ServiceNow Core ohne HAM Pro und SAM Pro, gebaut und getestet auf einer persönlichen Entwicklerinstanz (Release Brazil). Fundament mit einheitlichem Ergebnis-Vertrag, Modul 1 «Leaver Asset Return» (Rückgabe der Geräte bei Austritten, Nachweis für ISO 27001 A.5.11), Modul 2 «Asset↔CI Drift & DQ Scorecard». Diese Seite listet jedes Artefakt der App; Grenzen stehen in [`limitations.md`](limitations.md).

Everything below is part of the app's update set and is built from the sources in [`toolkit/`](../toolkit/) by [`toolkit/build_bundle.py`](../toolkit/build_bundle.py). The scope contains the instance's vendor prefix (`x_371499_itamkit`); the scripts never hard-code it, [`ItamKitConfig`](../toolkit/script_includes/ItamKitConfig.js) derives every table, property and event name from the running scope.

## Foundation

| Item | What |
|---|---|
| App | «ITAM Toolkit» 0.1.0, scoped, ECMAScript 2021 mode, runtime access tracking «Tracking» (see limitations) |
| Roles | `x_371499_itamkit.user` (read cases, scorecard, findings; work return tasks), `x_371499_itamkit.admin` (contains user; rules, drift fix, REST writes) |
| ACLs | 28, created by the platform with the tables (read/write/create/delete per table, role `user`) |
| Output contract | [`ItamKitResult`](../toolkit/script_includes/ItamKitResult.js): every entry point returns `{success, status_code, message, data}` |
| Query guard | [`ItamKitQuery`](../toolkit/script_includes/ItamKitQuery.js): every configurable encoded query is checked field by field; unknown fields are rejected with 422, because ServiceNow silently drops them |
| Audit log | [`ItamKitAudit`](../toolkit/script_includes/ItamKitAudit.js), table `…_audit_log`: one row per field the toolkit changes on a record it does not own, with old and new value, leading side and reason |
| REST API | «ITAM Toolkit», base path `/api/x_371499_itamkit/toolkit`, shared code in [`ItamKitRest`](../toolkit/script_includes/ItamKitRest.js) |
| Menu | «ITAM Toolkit»: leaver cases, return tasks, drift findings, DQ scorecards, rules, snapshots, audit log, properties |

### Status codes of the contract

| Code | Meaning |
|---|---|
| 200 | done |
| 201 | created (case, snapshot) |
| 204 | nothing to do (for example a leaver without hardware) |
| 208 | already done: idempotent repeat, nothing changed |
| 400 | invalid input (unknown outcome, missing leading side) |
| 403 | caller lacks the toolkit role (REST) |
| 404 | record not found |
| 409 | conflict with the current state (task already closed with another outcome, drift still present after the fix) |
| 422 | configuration invalid (query with an unknown field, invalid rule) |
| 500 | unexpected error, logged with the context |

The REST API sends the contract as body with the code as HTTP status; 204 and 208 go out as HTTP 200 so the body arrives.

### REST resources

| Method and path | Role | Returns |
|---|---|---|
| `GET /health` | user | app name and version |
| `GET /dq/scorecard?name=` | user | latest snapshot of a scorecard with every rule result and rule definition |
| `POST /dq/run?name=` | admin | drift scan for the scorecard's company, then a new snapshot |
| `GET /drift/mapping` | user | the OOTB asset/CI status mapping the drift watcher uses |
| `GET /leaver/kpi?company=` | user | return rate and cycle time of closed leaver cases |
| `POST /leaver/resolve` | admin | body `{user, last_working_day}`: opens the leaver case (for an HR system) |

### Cross-scope privileges

Declared explicitly in the app (26), each verified by the ATF tests:

| Target | Operations | Why |
|---|---|---|
| `sys_user` | read | leaver, manager, HR contact; DQ rules on users |
| `alm_hardware` | read, write | assets of the leaver, end state of a return, drift fix (CI leads) |
| `alm_asset` | read | asset fields reached through references |
| `asset_task` | read, write, create | return tasks |
| `cmdb_ci` | read, write | CI status, drift fix (asset leads) |
| `cmdb_ci_hardware`, `cmdb_model`, `core_company` | read | DQ rules, scorecard company |
| `alm_asset_ci_state_mapping` | read | target state of the drift watcher |
| `sys_choice`, `sys_scope` | read | labels in previews, version in `GET /health` |
| `sys_user` (create, write), `cmdb_ci_computer`, `alm_hardware`, `core_company`, `cmdb_hardware_product_model` (create) | | ATF only: the tests create their own data, rolled back after the run |
| APIs `GlideRecord.setValue`, `.insert`, `.update`, `Glide API: properties`, `ScopedGlideElement` | execute | found by switching the app to «Enforcing» (see limitations) |

## Module 1: Leaver Asset Return

Asset return compliance for ServiceNow Core: every leaver gets a case, every device still assigned to the leaver a return task, and the case closes with a measurable result. It is not an offboarding app (no accounts, no HR process), only the IT asset side of it.

| Item | What |
|---|---|
| Table `…_leaver_case` | extends `task`, number prefix LVR; leaver, last working day (and whether it is estimated), manager, HR contact, optional private contact address, trigger, counters (assets, returned, missing/lost, open), return rate, cycle time, last reminder, escalated |
| Return tasks | the platform table `asset_task` (exists on Core), parent = case; the app adds one column, `x_371499_itamkit_return_outcome` |
| Script include [`LeaverAssetResolver`](../toolkit/script_includes/LeaverAssetResolver.js) | `resolve`, `syncTasks`, `completeReturn`, `prepareReportedCase`, `sweep`, `sendDueReminders`, `kpis`; idempotent (a second call answers 208) |
| Trigger (a): record producer «Austritt melden» | catalog Hardware; HR enters the leaver, the last working day, an optional private address and a note; an open case for the same leaver is updated instead of creating a second one ([script](../toolkit/record_producers/austritt_melden.js)) |
| Trigger (b): business rule «leaver on deactivation» | `sys_user`, after update, `active` changes to false ([script](../toolkit/business_rules/user_deactivated.js)) |
| Trigger (c): scheduled job «leaver sweep» | daily 01:30: inactive users with hardware but no open case (deactivations that bypassed the rule, for example imports), resync of open cases, reminders ([script](../toolkit/scheduled_jobs/leaver_sweep.js)) |
| Business rule «create return tasks» | case, after insert: one `asset_task` per assigned device ([script](../toolkit/business_rules/leaver_case_sync_tasks.js)) |
| End states (UI actions on `asset_task`) | «Returned: in stock» (In stock / Available), «Returned: needs repair» (In stock / Pending repair), «Returned: for disposal» (In stock / Pending disposal), «Missing / lost» (Missing / Lost, assignment kept as evidence); all OOTB values of `alm_asset.install_status`/`substatus`, checked on the instance |
| Reminders | days 3, 7, 14 after the last working day (property `leaver.reminder_days`); to the manager and the HR contact (the leaver is inactive and gets no mail), plus the optional private address; day 14 is the escalation: also to the manager's manager (`sys_user.manager`), case priority high |
| Events and notifications | `x_371499_itamkit.leaver.reminder`, `….leaver.escalation`; notifications with the open devices (mail script `itamkit_open_returns`) |
| KPIs | return rate = returned / assets of closed cases; cycle time = calendar days from the last working day to closure; on time = closed by the escalation day; `GET /leaver/kpi` and reports «leaver cases by state», «return outcomes», «leaver cycle time» |
| Properties | `leaver.reminder_days` (3,7,14), `leaver.asset_query` (which assigned assets count; checked by the query guard), `leaver.assignment_group` |
| ATF «ITAM Toolkit: leaver asset return» | 76 assertions: three triggers, four end states, idempotency, a later HR report moves the due date, 204/400/404/409, reminders day 7 and escalation day 14, KPIs, query guard ([script](../toolkit/atf/leaver_asset_return.js)) |

Evidence for ISO/IEC 27001:2022 control A.5.11 (return of assets): per leaver a case with the list of devices, the outcome per device, timestamps, reminders in the work notes and the KPIs above.

## Module 2: Asset↔CI Drift & DQ Scorecard

| Item | What |
|---|---|
| Table `…_dq_rule` | code, name, group, dimension, weight, table, rule type, population and defect condition (condition builder), field and compare field, company field, remediation hint |
| Rule types | `query` (population AND defect condition), `duplicate` (surplus records sharing a value), `field_mismatch` (two fields, dot-walk allowed, both set and different), `drift` (asset/CI status) |
| 15 generic rules | fix script «seed generic DQ rules» ([source](../toolkit/fix_scripts/seed_dq_rules.js)); no company names, no customer data; C01–C08 on `cmdb_ci_hardware`, A01–A04 and X01 on `alm_hardware`, U01–U02 on `sys_user` |
| Tables `…_dq_scorecard`, `…_dq_snapshot`, `…_dq_result` | a scorecard can be limited to a company; every run writes a snapshot and one result per rule |
| Score | rule score = 100 × (1 − defects / population); scorecard score = Σ weight × rule score / Σ weight; rules without population are skipped, invalid rules are reported (422) and not counted |
| Script include [`DqScorecard`](../toolkit/script_includes/DqScorecard.js) | `run`, `evaluate`, `latest` |
| Script include [`AssetCiDrift`](../toolkit/script_includes/AssetCiDrift.js) | target state = OOTB table `alm_asset_ci_state_mapping` (52 entries on the PDI); `scan`, `fix`, `count` |
| Table `…_drift_finding` | asset, CI, observed states, expected CI status, preview for both leading sides, leading side, state, resolution |
| UI action «Drift beheben» | the leading side must be chosen; a dialog shows the preview of exactly that change; the fix writes the audit log and is verified afterwards (409 if the drift remains) |
| Scheduled job «drift scan and DQ snapshot» | daily 02:00 per active scorecard ([script](../toolkit/scheduled_jobs/dq_nightly.js)) |
| Reports | «DQ score trend» (line over the creation date, one point per day, no Performance Analytics), «DQ score per snapshot» (bar per snapshot) |
| Python check [`loader/check_dq_scorecard.py`](../loader/check_dq_scorecard.py) | own encoded-query evaluator, recomputes every rule from the raw records via the Table API and compares population, defects and score; cross-check with the ground truth of the test data |
| ATF «ITAM Toolkit: asset/CI drift and DQ scorecard» | 45 assertions: mapping, scan, fix with either side, audit row, idempotency, four rule types, invalid rule, weighted score ([script](../toolkit/atf/drift_and_scorecard.js)) |

### The 15 rules

| Code | Rule | Dimension | Weight |
|---|---|---|---:|
| C01 | CI without serial number | completeness | 3 |
| C02 | CI without location | completeness | 2 |
| C03 | Duplicate serial number | uniqueness | 3 |
| C04 | Manufacturer differs from the model's manufacturer | consistency | 2 |
| C05 | End-user device in use without assigned user | completeness | 3 |
| C06 | Retired end-user device still assigned | consistency | 2 |
| C07 | Device in use by an inactive user (leaver) | consistency | 3 |
| C08 | CI without model | completeness | 1 |
| A01 | Hardware asset without serial number | completeness | 2 |
| A02 | Active asset without warranty date | completeness | 1 |
| A03 | Duplicate asset tag | uniqueness | 2 |
| A04 | Asset in stock or retired but still assigned | consistency | 2 |
| X01 | Asset status differs from CI status (OOTB mapping) | consistency | 3 |
| U01 | Active user without manager | completeness | 2 |
| U02 | Active user without department | completeness | 1 |

C07 links the two modules: a device in use by an inactive user is the leaver backlog; U01 tells whether module 1 can escalate at all.

## Install on another instance

1. Import `servicenow/update_sets/ITAM_Toolkit_0.1.0.xml` (System Update Sets → Retrieved Update Sets → Import Update Set from XML), preview, commit. The vendor prefix is part of the scope; another instance gets the app under the same scope name.
2. Run the fix script «ITAM Toolkit: seed generic DQ rules» once (15 rules, scorecard «All companies»).
3. Assign the roles; optionally set `leaver.assignment_group` and the reminder days; create a scorecard per company.
4. Run both ATF tests.

For development the app is deployed from the sources: `python3 toolkit/build_bundle.py --out bundle.json` builds 218 records, a small deployer in an admin browser session upserts them through the Table API into the app's scope and update set.
