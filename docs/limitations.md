# ITAM Toolkit 0.1.0: limitations

> **Kurzfassung:** Was das Toolkit nicht kann, was auf der Entwicklerinstanz nicht ging und was in der Demo simuliert ist. Alles hier ist auf einer persönlichen Entwicklerinstanz (PDI, Release Brazil) mit erfundenen Daten der «Muster AG» entstanden, nicht in einem Kundenprojekt.

## Scope of the evidence

- Built and tested on one personal developer instance, release Brazil, with fictitious data. No customer project, no production load, no performance test beyond the PDI (about 1,100 hardware assets; the 15 rules evaluate the whole instance in about 3 seconds).
- HAM Pro, SAM Pro and the CMDB success advisor for HAM are not installed on the PDI. The comparisons in the README are based on ServiceNow and vendor documentation, not on hands-on tests.

## Platform findings that shaped the design

| Finding on the PDI | Consequence |
|---|---|
| **Runtime access tracking «Enforcing»** gates not only tables but also Glide APIs: `GlideRecord.setValue`, `GlideRecord.insert`, `GlideRecord.update`, `Glide API: properties`, `ScopedGlideElement` were each denied one after the other. Worse, the duplicate rule then returned 4 defects instead of 1 **without an error**. | 0.1.0 runs in «Tracking» (the platform default). The 21 table privileges and the 5 API privileges found so far are declared explicitly in the app. A complete «Enforcing» allow-list is open; a silent miscount is worse than a missing feature. |
| The OOTB synchronisation copies an asset's status to its CI, but a CI status written by an integration does **not** flow back to the asset (verified in the ATF test and in the demo). | Drift is realistic even with all business rules active; the drift watcher compares against `alm_asset_ci_state_mapping` instead of trusting the sync. On the PDI's own demo data (not Muster AG) the drift rule finds 120 of 1,091 assets. |
| Scoped apps may not call `setWorkflow(false)` on global tables. | The ATF test simulates a deactivation that bypassed the business rule with a user inserted as inactive (like an HR import). |
| A scoped app may not add list or form layouts to the global table `asset_task`. | The return task related list uses the asset_task default layout; the outcome is set by the four buttons and visible in the work notes, the case counters and the report «return outcomes». |
| `sysevent` is not readable from a scoped app. | `sendDueReminders()` returns the recipients per case; the ATF test checks them there. |
| ServiceNow silently ignores encoded-query terms with unknown fields (it cost this project an unwanted mass update earlier). | Every configurable query goes through `ItamKitQuery`; invalid rules are reported with 422 and not counted. |
| Trend reports have no unit finer than an hour; published reports are disabled on the PDI. | «DQ score trend» shows one point per day (the nightly snapshot); several snapshots on one day are shown by «DQ score per snapshot». |

## E-mail

Outbound e-mail is switched off on the PDI (`glide.email.smtp.active = false`). The reminder of the demo exists as `sys_email` record (Outbox, type *send-ready*, recipients HR contact and private address); it was never sent. Whether the mail reaches an inbox is not tested.

## Module 1

- No integration with an HR system; trigger (a) is the record producer, an HR system could call `POST /leaver/resolve`.
- The last working day is only known when HR reports it. For triggers (b) and (c) the case uses the day the toolkit noticed the leaver and marks it as estimated; reminders and cycle time count from that day.
- No user in the Muster AG test data has a manager (rule U01: 126 of 126). The demo reminder therefore went to the HR contact and the private address only; manager and escalation are covered by the ATF test with its own users.
- Only hardware (`alm_hardware`); licences and consumables are not reclaimed. No shipping labels, no pickup scheduling (HAM Pro has reclamation tasks for that).
- No Flow Designer: the logic is in script includes, a business rule and a scheduled job, so it can be tested with ATF and versioned as source.

## Module 2

- `field_mismatch` iterates the records of the population; on large tables a nightly run will be slow. `query` and `duplicate` use aggregates.
- Duplicates are counted on the exact database value (case-insensitive collation); serial numbers in another spelling are only caught if the import normalises them (this project's import does).
- The drift watcher compares the install status only, not the other fields of `alm_asset_ci_field_mapping`.
- «Drift beheben» fixes one finding at a time; there is no bulk fix on purpose (every fix is previewed and audited).

## Demo data

- The demo changed Muster AG data on the PDI: the devices of all four leavers were returned (three) or reported lost (one) through module 1, and two CI statuses were changed by `loader/simulate_drift.py` through the integration user to reproduce an integration update, then fixed with «Drift beheben» (one with the asset leading, one with the CI leading). The «53 of 53» result of `loader/check_data_quality.py` refers to the final run before the toolkit demo; a run today counts the four remediated leaver devices as no longer present.
- `loader/check_dq_scorecard.py` compares a snapshot with the live CMDB. The baseline report [`dq_scorecard_baseline.md`](dq_scorecard_baseline.md) keeps the result of the run right after the baseline snapshot; [`dq_scorecard.md`](dq_scorecard.md) is the run after the demo.
- The Python check reads the snapshot through the toolkit's REST API, which needs the role `x_371499_itamkit.user`. The integration user does not have it yet (role assignments are done by the instance owner); both checks ran with `--snapshot` from a saved REST answer, the raw records came live from the Table API.

## Delivery

- No ServiceNow Studio source control: linking needs a GitHub token on the PDI, which the owner decided against. The app is versioned as sources in `toolkit/` plus the update set export.
- The update set export contains the app; the Muster AG scorecard, the demo cases and snapshots are data and not part of it.
