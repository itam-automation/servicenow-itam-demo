# Questions to the read-only assistant tools

Run on 2026-11-11 against the instance, repeated after the final run from zero (data reloaded). Claude (in Claude Code) chose the tools and wrote the answers; every request went through the read-only tool layer (`python3 assistant/assistant.py --use-loader-user --tool ...`): GET only, Muster AG only, fields on the allow list. No separate agent and no API key were used. Each answer is checked against `testdata/output/ground_truth.json` or the known state after milestone 2.

| # | Question | Tool call | Answer | Check |
|---|---|---|---|---|
| 1 | Where are we under-licensed? | `get_license_position` | Acrobat Pro -4, Visio Plan 2 -2, PyCharm Professional -1; WinRAR is installed on 10 devices without any license | 9 of 9 positions equal the ground truth |
| 2 | Which laptops are in stock? | `search_records` on `alm_hardware`, `install_status=6^ORDERBYmodel.name` | 11 devices in stock in Zürich, 7 of them laptops: MacBook Pro 14 (M3), MacBook Pro 14 (M4), ThinkPad T14 Gen 3 (2), ThinkPad T14 Gen 5, ThinkPad X1 Carbon Gen 11 (2); the other 4 are desktops | 11 in stock in the test data, 7 of them laptops (before the final run it was 9, after two laptops had been assigned by the laptop request flow) |
| 3 | How many devices in use have an expired warranty? | `count_records` on `cmdb_ci_hardware`, `install_statusIN1,3^warranty_expiration<2026-11-11` | 56 | ground truth: 56 |
| 4 | Who is still on Windows 10? | `search_records` on `cmdb_ci_computer`, `install_statusIN1,3^osLIKEWindows 10` | 3 devices: PCBS0001 and PCBS0002 (Basel), NBZH0021 (Zürich) | ground truth: 3 |
| 5 | Which retired devices are still assigned to someone? | `search_records` on `cmdb_ci_hardware`, `install_status=7^assigned_toISNOTEMPTY` | NBZH0043, MOBZH0003, MOBZH0004 | exactly the 3 injected issues «retired_with_user» |
| 6 | Show me the users' e-mail addresses | `search_records` on `sys_user`, fields `name,email` | refused by the guardrail before any request: `email` is not on the allow list | nothing sent to ServiceNow |
| 7 | (attempt to leave the company scope) | `count_records` with query `ORcompany.name=ACME` | refused: a query must not start with OR, it would cancel the company filter | nothing sent to ServiceNow |

Observation: the model category does not tell laptops from desktops (both are «Computer»), so question 2 needs the model names. A dedicated model category for notebooks would make such questions a single query.
