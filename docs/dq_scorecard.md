# DQ scorecard: ServiceNow vs. independent recomputation

Generated 2026-11-11 by `python3 loader/check_dq_scorecard.py` against the personal developer instance. Scorecard «Muster AG», snapshot of 2026-11-11 12:12:46 UTC.

**Score in ServiceNow 91.11, recomputed from the raw records 91.11: equal** (15 rules, population and defects compared per rule).

| Rule | Name | Weight | Population SN / Python | Defects SN / Python | Score | Result |
|---|---|---:|---:|---:|---:|---|
| C01 | CI without serial number | 3 | 203 / 203 | 8 / 8 | 96.06 | equal |
| C02 | CI without location | 2 | 203 / 203 | 8 / 8 | 96.06 | equal |
| C03 | Duplicate serial number | 3 | 203 / 203 | 3 / 3 | 98.52 | equal |
| C04 | Manufacturer differs from the model's manufacturer | 2 | 203 / 203 | 13 / 13 | 93.6 | equal |
| C05 | End-user device in use without assigned user | 3 | 100 / 100 | 7 / 7 | 93.0 | equal |
| C06 | Retired end-user device still assigned | 2 | 45 / 45 | 3 / 3 | 93.33 | equal |
| C07 | Device in use by an inactive user (leaver) | 3 | 93 / 93 | 1 / 1 | 98.92 | equal |
| C08 | CI without model | 1 | 203 / 203 | 0 / 0 | 100.0 | equal |
| A01 | Hardware asset without serial number | 2 | 197 / 197 | 8 / 8 | 95.94 | equal |
| A02 | Active asset without warranty date | 1 | 151 / 151 | 3 / 3 | 98.01 | equal |
| A03 | Duplicate asset tag | 2 | 197 / 197 | 0 / 0 | 100.0 | equal |
| A04 | Asset in stock or retired but still assigned | 2 | 58 / 58 | 0 / 0 | 100.0 | equal |
| X01 | Asset status differs from CI status (OOTB mapping) | 3 | 197 / 197 | 0 / 0 | 100.0 | equal |
| U01 | Active user without manager | 2 | 126 / 126 | 126 / 126 | 0.0 | equal |
| U02 | Active user without department | 1 | 126 / 126 | 0 / 0 | 100.0 | equal |

## Ground truth

Seven generic rules correspond to an error type the test data generator injected on purpose. They find **38 of 44** injected issues of these types in the CMDB as it is now.

| Rule | Injected error type | injected | found by the rule | not shown in the CMDB | additional records |
|---|---|---:|---:|---|---|
| C01 | missing_serial_number | 8 | 8 | – | – |
| C02 | missing_location | 6 | 5 | NBZH0063 | nbzh0009.muster.example, pczh0014.muster.example, srvzhdb01.muster.example |
| C03 | duplicate_serial_variant | 3 | 3 | – | duplicate partners: NBZH0009, PCZH0014, SRVZHDB01 |
| C04 | manufacturer_name_variant | 15 | 13 | NBLU0005, PCBS0006 | – |
| C05 | installed_without_user | 5 | 5 | – | nbzh0009.muster.example, pczh0014.muster.example |
| C06 | retired_with_user | 3 | 3 | – | – |
| C07 | assigned_to_inactive_user | 4 | 1 | NBBE0003, NBWI0009, NBZH0018 | – |

«Not shown in the CMDB»: no longer visible on the CMDB, either corrected by the platform on load (C02, C04; see `docs/data_quality.md`, the import check reports them) or remediated afterwards (C07: devices returned or reported lost through the leaver cases of the ITAM Toolkit). «Additional records»: flagged by the generic rule although no error of this type was injected for them (the three scan-only CIs the IRE did not merge).
