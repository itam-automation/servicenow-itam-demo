# Data quality: measured against the ground truth

Generated 2026-11-11 by `python3 loader/check_data_quality.py` against the personal developer instance: 203 CIs of Muster AG. The test data generator injected 53 issues on purpose (`testdata/output/ground_truth.json`); this check classifies how each one was caught.

**53 of 53 injected data quality issues detected** (9 merged by the IRE, 41 found by the reports on the CMDB, 3 reported by the import check on the source data); 0 resolved by the platform without a report, 0 not detected.

| Issue type | injected | IRE | Report | Import check | Platform | not detected |
|---|---:|---:|---:|---:|---:|---:|
| Missing serial number | 8 | 0 | 8 | 0 | 0 | 0 |
| Missing location | 6 | 0 | 5 | 1 | 0 | 0 |
| Manufacturer name variant (e.g. «DELL») | 15 | 0 | 13 | 2 | 0 | 0 |
| Endpoint in use without assigned user | 5 | 0 | 5 | 0 | 0 | 0 |
| Retired endpoint still assigned | 3 | 0 | 3 | 0 | 0 | 0 |
| In use by an inactive user (leaver) | 4 | 0 | 4 | 0 | 0 | 0 |
| Duplicate from scan: same serial, FQDN name | 6 | 6 | 0 | 0 | 0 | 0 |
| Duplicate from scan: serial in other spelling, other MAC | 3 | 0 | 3 | 0 | 0 | 0 |
| Duplicate from scan: same name, no serial | 3 | 3 | 0 | 0 | 0 | 0 |

Details:

- NBZH0063 (Missing location): Import check, corrected by the platform on load (location taken over from the assigned user), reported by the import check as location_missing
- NBLU0005 (Manufacturer name variant (e.g. «DELL»)): Import check, corrected by the platform on load («LENOVO» differs only in case, matched to existing «Lenovo» on load), reported by the import check as manufacturer_mismatch
- PCBS0006 (Manufacturer name variant (e.g. «DELL»)): Import check, corrected by the platform on load («LENOVO» differs only in case, matched to existing «Lenovo» on load), reported by the import check as manufacturer_mismatch
- nbzh0009.muster.example (Duplicate from scan: serial in other spelling, other MAC): Report, separate CI, found by duplicate check
- srvzhdb01.muster.example (Duplicate from scan: serial in other spelling, other MAC): Report, separate CI, found by duplicate check
- pczh0014.muster.example (Duplicate from scan: serial in other spelling, other MAC): Report, separate CI, found by duplicate check

The import check (rules «location missing in the inventory export» and «manufacturer differs from the model master data») flags 21 of the 21 injected issues of these two types on its own; the reports on the CMDB find 18 of them, the import check adds the ones the CMDB no longer shows.

| KPI | expected | in ServiceNow |
|---|---:|---:|
| Warranty ends in 2027 (in use) | 22 | 22 |
| Warranty expired (in use) | 56 | 56 |
| Windows 10 (in use) | 3 | 3 |
