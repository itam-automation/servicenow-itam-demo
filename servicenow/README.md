# Configuration on the instance

Everything the loader relies on, created as admin on the developer instance (release Brazil) and captured in the update set **«ITAM Demo - Baustein 2 CMDB-Import»**.

| Item | Table | Details |
|---|---|---|
| IRE data sources | `sys_choice` (cmdb_ci.discovery_source) | `MusterInventar` (inventory export), `MusterNetzScan` (network scan) |
| Reconciliation rule | `cmdb_reconciliation_definition` | applies to `cmdb_ci_hardware`; `MusterInventar` is authoritative for name, asset tag, assigned to, location, department, company, install status, cost, purchase date, warranty expiration |
| Staging tables | `sys_db_object` (extends `sys_import_set_row`) | `u_muster_location_imp`, `u_muster_department_imp`, `u_muster_user_imp`, `u_muster_model_imp`, `u_muster_device_imp` |
| Transform maps | `sys_transform_map` | master data with field maps and coalesce; devices with the onBefore script [`device_transform_onbefore.js`](device_transform_onbefore.js); model category via [`model_category_source_script.js`](model_category_source_script.js) |
| Reports | `sys_report` | «ITAM DQ 1–7» (data quality rules) and «ITAM KPI» (warranty 2027, warranty expired, CIs by status) on `cmdb_ci_hardware`, filtered on company Muster AG |
| Integration user | `sys_user` | `svc_itam_loader`, identity type machine, web service access only; roles `sn_cmdb_editor`, `import_transformer`, `import_set_loader`, `user_admin`, `model_manager` |

The staging tables and transform maps are generated from one definition, [`loader/staging.py`](../loader/staging.py) (`python3 loader/staging.py` prints the full specification including the scripts). Exporting the update set as XML into this folder is planned for milestone 2.
