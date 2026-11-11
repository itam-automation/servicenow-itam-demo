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

Milestone 2, captured in the update set **«ITAM Demo - Meilenstein 2 Laptop-Anforderung»**:

| Item | Table | Details |
|---|---|---|
| Catalog item «Laptop anfordern» | `sc_cat_item`, `item_option_new`, `question_choice` | category Hardware; variables `requested_for` (Requested For), `laptop_model` (select box: ThinkPad T14 Gen 5, ThinkPad X1 Carbon Gen 11, MacBook Pro 14 (M4)), `justification` |
| Flow «Laptop anfordern» | `sys_hub_flow` (Flow Designer) | service catalog trigger; approval by group, look up stock asset, update asset (*In use* + assigned to), catalog task; else procurement task |
| Business rule «ITAM: Lifecycle-Status Hardware-Asset» | `sys_script` on `alm_hardware` | [`business_rule_asset_lifecycle.js`](business_rule_asset_lifecycle.js) |
| Fix script «ITAM: Asset-Status an CI angleichen» | `sys_script_fix` | [`fix_asset_status_from_ci.js`](fix_asset_status_from_ci.js), run once |
| ATF test «ITAM: Lifecycle-Status Hardware-Asset» | `sys_atf_test`, `sys_atf_step` | [`atf_lifecycle_test.js`](atf_lifecycle_test.js); test execution enabled via `sn_atf.runner.enabled` |
| Group «Muster AG IT-Asset-Management» | `sys_user_group` (data, not in the update set) | approver and assignment group; member: admin |

Milestone 3 (software asset management), captured in the update set **«ITAM Demo - Meilenstein 3 SAM»**:

| Item | Table | Details |
|---|---|---|
| Script include «MusterSamImport» | `sys_script_include` | [`sam_import_utils.js`](sam_import_utils.js): lookups for the field maps (manufacturer, license type, software model, package, device) |
| Script include «ItamLicensePosition» | `sys_script_include` | [`license_position.js`](license_position.js): license position per software model |
| Staging tables | `sys_db_object` | `u_muster_software_imp`, `u_muster_installation_imp`, `u_muster_license_imp` |
| Transform maps | `sys_transform_map` | software -> `cmdb_software_product_model` (onAfter [`software_transform_onafter.js`](software_transform_onafter.js) creates the packages); installations -> `cmdb_software_instance` (coalesce on package and device, onBefore [`installation_transform_onbefore.js`](installation_transform_onbefore.js)); licenses -> `alm_license` (onComplete [`license_transform_oncomplete.js`](license_transform_oncomplete.js) recalculates the position) |
| Table «ITAM Lizenzposition» | `u_itam_license_position` | company, software model, publisher, license type, rights, usage, difference, status; list layout |
| Scheduled job «ITAM: Lizenzposition berechnen» | `sysauto_script` | daily, `new ItamLicensePosition('Muster AG').store()` |
| Reports | `sys_report` | «ITAM SAM 1 - Lizenzposition Muster AG» (list), «ITAM SAM 2 - Produkte nach Lizenzstatus» (bar) |
| Scripted REST API «ITAM Demo» | `sys_ws_definition`, `sys_ws_operation` | `GET /license_position`, [`rest_license_position.js`](rest_license_position.js); requires authentication and the default REST ACL; the base path contains the instance's namespace and is configured in `.env` (`SN_ITAM_API`) |
| Column types of the staging tables | `sys_dictionary` | set to `string` by name (they had been created with the type's sys_id) |

The staging tables and transform maps are generated from one definition, [`loader/staging.py`](../loader/staging.py) (`python3 loader/staging.py` prints the full specification including the scripts).

## Update sets as XML

Both update sets are exported in [`update_sets/`](update_sets/):

| File | Content |
|---|---|
| `ITAM_Demo_Baustein2_CMDB-Import.xml` | 152 customer updates: data sources, reconciliation rule, 5 staging tables with columns, 5 transform maps with field maps and scripts, 10 reports |
| `ITAM_Demo_Meilenstein2_Laptop-Anforderung.xml` | 15 customer updates: catalog item with variables, flow, business rule, fix script, ATF test, ATF property |

To install on another instance: *System Update Sets → Retrieved Update Sets → Import Update Set from XML*, then *Preview* and *Commit* (first Baustein 2, then Meilenstein 2). The group «Muster AG IT-Asset-Management» is data and has to be created separately.
