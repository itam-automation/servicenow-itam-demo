# DQ scorecard: ServiceNow vs. independent recomputation (baseline)

Run on 2026-11-11 at about 12:00 UTC by `python3 loader/check_dq_scorecard.py --snapshot docs/evidence/dq_snapshot_baseline.json`, right after the baseline snapshot and before module 1 and the drift demo changed Muster AG data. The script compares with the live CMDB, so a re-run today compares this snapshot with the changed data; this file keeps the result of the run at the time (console output of that run, written down unchanged). Scorecard «Muster AG», snapshot of 2026-11-11 11:54:42 UTC.

**Score in ServiceNow 90.84, recomputed from the raw records 90.84: equal** (15 rules, population and defects compared per rule).

| Rule | Name | Weight | Population SN / Python | Defects SN / Python | Score | Result |
|---|---|---:|---:|---:|---:|---|
| C01 | CI without serial number | 3 | 203 / 203 | 8 / 8 | 96.06 | equal |
| C02 | CI without location | 2 | 203 / 203 | 8 / 8 | 96.06 | equal |
| C03 | Duplicate serial number | 3 | 203 / 203 | 3 / 3 | 98.52 | equal |
| C04 | Manufacturer differs from the model's manufacturer | 2 | 203 / 203 | 13 / 13 | 93.6 | equal |
| C05 | End-user device in use without assigned user | 3 | 103 / 103 | 7 / 7 | 93.2 | equal |
| C06 | Retired end-user device still assigned | 2 | 45 / 45 | 3 / 3 | 93.33 | equal |
| C07 | Device in use by an inactive user (leaver) | 3 | 96 / 96 | 4 / 4 | 95.83 | equal |
| C08 | CI without model | 1 | 203 / 203 | 0 / 0 | 100 | equal |
| A01 | Hardware asset without serial number | 2 | 197 / 197 | 8 / 8 | 95.94 | equal |
| A02 | Active asset without warranty date | 1 | 152 / 152 | 3 / 3 | 98.03 | equal |
| A03 | Duplicate asset tag | 2 | 197 / 197 | 0 / 0 | 100 | equal |
| A04 | Asset in stock or retired but still assigned | 2 | 56 / 56 | 0 / 0 | 100 | equal |
| X01 | Asset status differs from CI status (OOTB mapping) | 3 | 197 / 197 | 0 / 0 | 100 | equal |
| U01 | Active user without manager | 2 | 126 / 126 | 126 / 126 | 0 | equal |
| U02 | Active user without department | 1 | 126 / 126 | 0 / 0 | 100 | equal |

## Ground truth

Seven generic rules correspond to an error type the test data generator injected on purpose. They find **41 of 44** injected issues of these types in the CMDB as it was at the baseline.

| Rule | Injected error type | injected | found by the rule | not shown in the CMDB | additional records |
|---|---|---:|---:|---|---|
| C01 | missing_serial_number | 8 | 8 | – | – |
| C02 | missing_location | 6 | 5 | NBZH0063 | nbzh0009.muster.example, pczh0014.muster.example, srvzhdb01.muster.example |
| C03 | duplicate_serial_variant | 3 | 3 | – | duplicate partners: NBZH0009, PCZH0014, SRVZHDB01 |
| C04 | manufacturer_name_variant | 15 | 13 | NBLU0005, PCBS0006 | – |
| C05 | installed_without_user | 5 | 5 | – | nbzh0009.muster.example, pczh0014.muster.example |
| C06 | retired_with_user | 3 | 3 | – | – |
| C07 | assigned_to_inactive_user | 4 | 4 | – | – |

«Not shown in the CMDB»: corrected by the platform on load (see `docs/data_quality.md`; the import check reports these 3). «Additional records»: flagged by the generic rule although no error of this type was injected for them (the three scan-only CIs the IRE did not merge). Together with the 3 the import check reports, the generic rules account for the same 44 issues of these seven types as the project's own reports and import check.
