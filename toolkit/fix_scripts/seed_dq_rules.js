/**
 * Fix script «ITAM Toolkit: seed generic DQ rules».
 * 15 generic rules on base tables (no customer data, no company names) and the scorecard
 * «All companies». Idempotent: rules are matched by code; existing rules keep their
 * active flag and weight, everything else is refreshed. Run once after installing the app.
 */
(function () {
    const END_USER = 'sys_class_nameINcmdb_ci_computer,cmdb_ci_hardware';
    const RULES = [
        // code, group, dimension, weight, table, type, population, defect, field, compare, name, remediation
        ['C01', 'ci', 'completeness', 3, 'cmdb_ci_hardware', 'query', '', 'serial_numberISEMPTY', '', '',
            'CI without serial number', 'Take the serial number from the inventory or discovery source; without it the IRE cannot match the device.'],
        ['C02', 'ci', 'completeness', 2, 'cmdb_ci_hardware', 'query', '', 'locationISEMPTY', '', '',
            'CI without location', 'Set the location in the authoritative source (inventory export), not in the CMDB.'],
        ['C03', 'ci', 'uniqueness', 3, 'cmdb_ci_hardware', 'duplicate', '', '', 'serial_number', '',
            'Duplicate serial number', 'Merge the duplicate CIs (CMDB de-duplication task) and check the identification rule of the source.'],
        ['C04', 'ci', 'consistency', 2, 'cmdb_ci_hardware', 'field_mismatch', '', '', 'manufacturer', 'model_id.manufacturer',
            'Manufacturer differs from the model\'s manufacturer', 'Normalise the manufacturer name (e.g. «DELL» -> «Dell Inc.») at the import.'],
        ['C05', 'ci', 'completeness', 3, 'cmdb_ci_hardware', 'query', END_USER + '^install_statusIN1,3', 'assigned_toISEMPTY', '', '',
            'End-user device in use without assigned user', 'Assign the user or set the device to In stock.'],
        ['C06', 'ci', 'consistency', 2, 'cmdb_ci_hardware', 'query', END_USER + '^install_status=7', 'assigned_toISNOTEMPTY', '', '',
            'Retired end-user device still assigned', 'Remove the assignment when retiring the device.'],
        ['C07', 'ci', 'consistency', 3, 'cmdb_ci_hardware', 'query', 'install_statusIN1,3^assigned_toISNOTEMPTY', 'assigned_to.active=false', '', '',
            'Device in use by an inactive user (leaver)', 'Open a leaver case (module 1) so the asset is returned.'],
        ['C08', 'ci', 'completeness', 1, 'cmdb_ci_hardware', 'query', '', 'model_idISEMPTY', '', '',
            'CI without model', 'Map the model at the import (model master data).'],
        ['A01', 'asset', 'completeness', 2, 'alm_hardware', 'query', '', 'serial_numberISEMPTY', '', '',
            'Hardware asset without serial number', 'Complete the serial number from the delivery note or the CI.'],
        ['A02', 'asset', 'completeness', 1, 'alm_hardware', 'query', 'install_statusIN1,3,6', 'warranty_expirationISEMPTY', '', '',
            'Active asset without warranty date', 'Enter the warranty end from the purchase order or the vendor portal.'],
        ['A03', 'asset', 'uniqueness', 2, 'alm_hardware', 'duplicate', '', '', 'asset_tag', '',
            'Duplicate asset tag', 'Re-label one of the devices; asset tags must be unique.'],
        ['A04', 'asset', 'consistency', 2, 'alm_hardware', 'query', 'install_statusIN6,7', 'assigned_toISNOTEMPTY', '', '',
            'Asset in stock or retired but still assigned', 'Clear the assignment; only assets in use are assigned.'],
        ['X01', 'asset_ci', 'consistency', 3, 'alm_hardware', 'drift', '', '', '', '',
            'Asset status differs from CI status (OOTB mapping)', 'Open the drift finding and fix it with the leading side.'],
        ['U01', 'user', 'completeness', 2, 'sys_user', 'query', 'active=true', 'managerISEMPTY', '', '',
            'Active user without manager', 'Maintain the manager in the HR source; escalations follow sys_user.manager.'],
        ['U02', 'user', 'completeness', 1, 'sys_user', 'query', 'active=true', 'departmentISEMPTY', '', '',
            'Active user without department', 'Maintain the department in the HR source.']
    ];

    const table = gs.getCurrentScopeName() + '_dq_rule';
    let created = 0;
    let updated = 0;
    RULES.forEach(function (r, i) {
        const rule = new GlideRecord(table);
        const exists = rule.get('code', r[0]);
        if (!exists) {
            rule.initialize();
            rule.setValue('code', r[0]);
            rule.setValue('active', true);
            rule.setValue('weight', r[3]);
        }
        rule.setValue('rule_group', r[1]);
        rule.setValue('dimension', r[2]);
        rule.setValue('table_name', r[4]);
        rule.setValue('rule_type', r[5]);
        rule.setValue('population_query', r[6]);
        rule.setValue('defect_query', r[7]);
        rule.setValue('field', r[8]);
        rule.setValue('compare_field', r[9]);
        rule.setValue('company_field', 'company');
        rule.setValue('name', r[10]);
        rule.setValue('remediation', r[11]);
        rule.setValue('order', (i + 1) * 10);
        if (exists) {
            rule.update();
            updated++;
        } else {
            rule.insert();
            created++;
        }
    });

    const card = new GlideRecord(gs.getCurrentScopeName() + '_dq_scorecard');
    if (!card.get('name', 'All companies')) {
        card.initialize();
        card.setValue('name', 'All companies');
        card.setValue('active', true);
        card.setValue('description', 'All records of the instance, no company filter.');
        card.insert();
    }
    gs.info('ITAM Toolkit DQ rules: ' + created + ' created, ' + updated + ' updated');
})();
