# Data quality: measured against the ground truth

Generated 2026-11-11 by `python3 loader/check_data_quality.py` against the personal developer instance: 203 CIs of Muster AG. The test data generator injected 53 issues on purpose (`testdata/output/ground_truth.json`); this check classifies how each one was caught.

**50 of 53 injected data quality issues detected** (9 merged by the IRE, 41 found by the reports); 3 were already resolved by the platform on load, 0 not detected.

| Issue type | injected | IRE | Report | Platform | not detected |
|---|---:|---:|---:|---:|---:|
| Missing serial number | 8 | 0 | 8 | 0 | 0 |
| Missing location | 6 | 0 | 5 | 1 | 0 |
| Manufacturer name variant (e.g. «DELL») | 15 | 0 | 13 | 2 | 0 |
| Endpoint in use without assigned user | 5 | 0 | 5 | 0 | 0 |
| Retired endpoint still assigned | 3 | 0 | 3 | 0 | 0 |
| In use by an inactive user (leaver) | 4 | 0 | 4 | 0 | 0 |
| Duplicate from scan: same serial, FQDN name | 6 | 6 | 0 | 0 | 0 |
| Duplicate from scan: serial in other spelling, other MAC | 3 | 0 | 3 | 0 | 0 |
| Duplicate from scan: same name, no serial | 3 | 3 | 0 | 0 | 0 |

Details:

- NBZH0063 (Missing location): Platform, location taken over from the assigned user
- NBLU0005 (Manufacturer name variant (e.g. «DELL»)): Platform, «LENOVO» differs only in case, matched to existing «Lenovo» on load
- PCBS0006 (Manufacturer name variant (e.g. «DELL»)): Platform, «LENOVO» differs only in case, matched to existing «Lenovo» on load
- nbzh0009.muster.example (Duplicate from scan: serial in other spelling, other MAC): Report, separate CI, found by duplicate check
- srvzhdb01.muster.example (Duplicate from scan: serial in other spelling, other MAC): Report, separate CI, found by duplicate check
- pczh0014.muster.example (Duplicate from scan: serial in other spelling, other MAC): Report, separate CI, found by duplicate check

| KPI | expected | in ServiceNow |
|---|---:|---:|
| Warranty ends in 2027 (in use) | 22 | 22 |
| Warranty expired (in use) | 56 | 56 |
| Windows 10 (in use) | 3 | 3 |
