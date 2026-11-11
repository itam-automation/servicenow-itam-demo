/**
 * ItamKitAudit: one row per change the toolkit makes to a record it does not own
 * (asset status after a return, CI or asset status after a drift fix).
 * Complements sys_audit: the row says why the toolkit changed the value and which
 * side was leading, not only that it changed.
 */
var ItamKitAudit = Class.create();

/**
 * entry: {module, action, table, id, display, field, oldValue, newValue, leadingSide, finding, note}
 * Returns the sys_id of the audit row.
 */
ItamKitAudit.log = function (entry) {
    const row = new GlideRecord(ItamKitConfig.table('audit_log'));
    row.initialize();
    row.setValue('module', entry.module || '');
    row.setValue('action', entry.action || '');
    row.setValue('target_table', entry.table || '');
    row.setValue('target_id', entry.id || '');
    row.setValue('target_display', entry.display || '');
    row.setValue('field', entry.field || '');
    row.setValue('old_value', entry.oldValue === undefined ? '' : String(entry.oldValue));
    row.setValue('new_value', entry.newValue === undefined ? '' : String(entry.newValue));
    row.setValue('leading_side', entry.leadingSide || '');
    if (entry.finding) row.setValue('finding', entry.finding);
    row.setValue('note', entry.note || '');
    return row.insert();
};

/** Logs every field whose value differs between two {field: value} snapshots. */
ItamKitAudit.logChanges = function (base, before, after) {
    let rows = 0;
    Object.keys(after).forEach(function (field) {
        if (String(before[field] || '') === String(after[field] || '')) return;
        ItamKitAudit.log(Object.assign({}, base, {field: field, oldValue: before[field], newValue: after[field]}));
        rows++;
    });
    return rows;
};

ItamKitAudit.prototype = {
    type: 'ItamKitAudit'
};
