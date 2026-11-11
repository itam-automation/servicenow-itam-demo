/**
 * ItamKitRequests: the scripted steps of the two catalog flows of ITAM Toolkit 0.2.0.
 *
 *   «Gerät zurückgeben oder tauschen»   approver -> start_return -> (return task closed) -> complete_return
 *   «Asset-Daten oder Standort ändern»  approver -> apply_change
 *   both, after a rejection             reject
 *
 * The flows call run(step, ritmId) through the custom action «ITAM Toolkit: run request step».
 * Every step returns the ItamKitResult contract {success, status_code, message, data}; data carries
 * approver_user, approver_group and return_task for the flow's data pills.
 */
var ItamKitRequests = Class.create();

/** Reason of a device return -> state of the returned device and whether a replacement is needed. */
ItamKitRequests.REASONS = {
    defekt: {replacement: true, state: '6', substatus: 'pending_repair', label: 'defective'},
    tausch: {replacement: true, state: '6', substatus: 'available', label: 'exchange'},
    nicht_benoetigt: {replacement: false, state: '6', substatus: 'available', label: 'no longer needed'}
};

/** Change type of a data change request -> asset field (the CI has a field of the same name). */
ItamKitRequests.CHANGES = {
    standort: {field: 'location', variable: 'new_location', label: 'location'},
    kostenstelle: {field: 'cost_center', variable: 'new_cost_center', label: 'cost center'},
    zuordnung: {field: 'assigned_to', variable: 'new_assigned_to', label: 'assigned user'}
};

ItamKitRequests.STEPS = ['approver', 'start_return', 'complete_return', 'apply_change', 'reject'];
ItamKitRequests.RITM_CLOSED_COMPLETE = '3';
ItamKitRequests.RITM_CLOSED_INCOMPLETE = '4';

ItamKitRequests.prototype = {
    initialize: function () {
        this.fallbackGroup = ItamKitConfig.prop('requests.fallback_group', '');
    },

    /** Entry point of the custom flow action. */
    run: function (step, ritmId) {
        try {
            if (ItamKitRequests.STEPS.indexOf(step) < 0) {
                return ItamKitResult.fail(400, 'Unknown step "' + step + '"; use one of ' + ItamKitRequests.STEPS.join(', '));
            }
            const ritm = new GlideRecord('sc_req_item');
            if (!ritmId || !ritm.get(ritmId)) return ItamKitResult.fail(404, 'Requested item not found: ' + ritmId);
            switch (step) {
                case 'approver': return this.approver(ritm);
                case 'start_return': return this.startReturn(ritm);
                case 'complete_return': return this.completeReturn(ritm);
                case 'apply_change': return this.applyChange(ritm);
                default: return this.reject(ritm);
            }
        } catch (e) {
            return ItamKitResult.fromError(e, 'ItamKitRequests.' + step);
        }
    },

    /**
     * Who approves. Return/exchange: the manager of the requested-for user. Data change: the asset owner,
     * then the head of the asset's department (Fachbereich). Without an active person: the fallback group
     * (property requests.fallback_group, a group name), so the request does not get stuck.
     */
    approver: function (ritm) {
        const isChange = this._isChange(ritm);
        let person = null;
        let source = '';
        if (isChange) {
            const asset = this._asset(ritm.variables.asset.toString());
            if (!asset) return ItamKitResult.fail(400, 'The request names no valid asset');
            if (this._activeUser(asset.owned_by)) {
                person = asset.owned_by;
                source = 'asset owner';
            } else if (this._activeUser(asset.department.dept_head)) {
                person = asset.department.dept_head;
                source = 'head of the department';
            }
        } else {
            const user = ritm.variables.requested_for.nil() ? ritm.requested_for : ritm.variables.requested_for;
            if (this._activeUser(user.manager)) {
                person = user.manager;
                source = 'manager of ' + user.getDisplayValue();
            }
        }
        const data = {approver_user: '', approver_group: '', source: source};
        if (person) {
            data.approver_user = person.toString();
            return ItamKitResult.ok(200, 'Approval by ' + person.getDisplayValue() + ' (' + source + ')', data);
        }
        const group = new GlideRecord('sys_user_group');
        if (!this.fallbackGroup || !group.get('name', this.fallbackGroup)) {
            return ItamKitResult.fail(422, 'No approver: nobody found and property requests.fallback_group names no group');
        }
        data.approver_group = group.getUniqueValue();
        data.source = 'fallback group';
        return ItamKitResult.ok(200, 'Approval by the group ' + group.getValue('name') + ' (no ' +
            (isChange ? 'asset owner or department head' : 'manager') + ' found)', data);
    },

    /** After the approval of a return: one return task, plus a replacement task for a defective or exchanged device. */
    startReturn: function (ritm) {
        const reason = ItamKitRequests.REASONS[ritm.variables.reason.toString()];
        if (!reason) return ItamKitResult.fail(400, 'Unknown reason "' + ritm.variables.reason + '"');
        const asset = this._asset(ritm.variables.device.toString());
        if (!asset) return ItamKitResult.fail(400, 'The request names no valid device');
        const userId = ritm.variables.requested_for.toString() || ritm.getValue('requested_for');
        if (asset.getValue('assigned_to') !== userId) {
            return ItamKitResult.fail(409, asset.getDisplayValue() + ' is not assigned to ' + ritm.variables.requested_for.getDisplayValue());
        }
        const existing = this._tasks(ritm);
        if (existing.return_task) {
            return ItamKitResult.ok(208, 'Tasks already exist for ' + ritm.getValue('number'), existing);
        }
        const returnTask = this._newTask(ritm, asset, 'Device return', 'Return ' + asset.getDisplayValue() + ' (' + reason.label + ')');
        let replacement = '';
        if (reason.replacement) {
            replacement = this._newTask(ritm, null, 'Device replacement', 'Provide a replacement for ' + asset.getDisplayValue() +
                ' (model ' + asset.model.getDisplayValue() + ')', asset.getValue('model'));
        }
        return ItamKitResult.ok(201, 'Return task' + (replacement ? ' and replacement task' : '') + ' created for ' + ritm.getValue('number'),
            {return_task: returnTask, replacement_task: replacement, approver_user: '', approver_group: ''});
    },

    /**
     * After the return task is closed: the returned device gets its state from the reason (OOTB values),
     * the assignment is removed, the CI is kept consistent with the OOTB asset/CI status mapping,
     * every change goes to the toolkit audit log, the requested item is closed.
     */
    completeReturn: function (ritm) {
        const tasks = this._tasks(ritm);
        const task = new GlideRecord('asset_task');
        if (!tasks.return_task || !task.get(tasks.return_task)) return ItamKitResult.fail(404, 'No return task for ' + ritm.getValue('number'));
        if (task.getValue('state') !== '3') return ItamKitResult.fail(409, task.getValue('number') + ' is not closed complete yet');
        const reason = ItamKitRequests.REASONS[ritm.variables.reason.toString()];
        const asset = this._asset(task.getValue('asset'));
        const base = {module: 'request', action: 'device_return', note: ritm.getValue('number') + ' (' + reason.label + ')'};

        const before = {install_status: asset.getValue('install_status'), substatus: asset.getValue('substatus'),
            assigned_to: asset.getValue('assigned_to')};
        if (before.install_status === reason.state && before.substatus === reason.substatus && !before.assigned_to) {
            return ItamKitResult.ok(208, asset.getDisplayValue() + ' is already returned');
        }
        asset.setValue('install_status', reason.state);
        asset.setValue('substatus', reason.substatus);
        asset.setValue('assigned_to', '');
        asset.update();
        asset.get(asset.getUniqueValue());
        let changes = ItamKitAudit.logChanges(Object.assign({table: 'alm_hardware', id: asset.getUniqueValue(), display: asset.getDisplayValue()}, base),
            before, {install_status: asset.getValue('install_status'), substatus: asset.getValue('substatus'),
                assigned_to: asset.getValue('assigned_to')});

        let ciNote = 'no CI';
        if (!asset.ci.nil()) {
            const drift = new AssetCiDrift();
            const expected = drift.expectedCiStatus(asset.getValue('install_status'), asset.getValue('substatus'));
            const ci = new GlideRecord('cmdb_ci');
            ci.get(asset.getValue('ci'));
            ciNote = 'CI ' + ci.getDisplayValue() + ' consistent';
            if (expected && ci.getValue('install_status') !== expected) {
                const old = ci.getValue('install_status');
                ci.setValue('install_status', expected);
                ci.update();
                changes += ItamKitAudit.logChanges(Object.assign({table: ci.getValue('sys_class_name'), id: ci.getUniqueValue(),
                    display: ci.getDisplayValue(), leadingSide: 'asset'}, base), {install_status: old}, {install_status: expected});
                ciNote = 'CI ' + ci.getDisplayValue() + ' set to the mapped status';
            }
        }
        this._close(ritm, ItamKitRequests.RITM_CLOSED_COMPLETE, 'Device returned (' + reason.label + '): ' + asset.getDisplayValue() +
            ' is ' + asset.install_status.getDisplayValue() + ' / ' + asset.substatus.getDisplayValue() + '; ' + ciNote + '.');
        return ItamKitResult.ok(200, asset.getDisplayValue() + ': ' + asset.install_status.getDisplayValue() + ' / ' +
            asset.substatus.getDisplayValue() + '; ' + ciNote + ' (' + changes + ' audit row(s))',
            {asset: asset.getDisplayValue(), audit_rows: changes});
    },

    /** After the approval of a data change: the asset and its CI get the new value; old and new go to the audit log. */
    applyChange: function (ritm) {
        const change = ItamKitRequests.CHANGES[ritm.variables.change_type.toString()];
        if (!change) return ItamKitResult.fail(400, 'Unknown change type "' + ritm.variables.change_type + '"');
        // the new-value variables are optional (only the one for the chosen change type is shown)
        const answer = ritm.variables[change.variable];
        const value = answer ? answer.toString() : '';
        if (!value) return ItamKitResult.fail(400, 'The request names no new ' + change.label);
        const asset = this._asset(ritm.variables.asset.toString());
        if (!asset) return ItamKitResult.fail(400, 'The request names no valid asset');
        const base = {module: 'request', action: 'data_change', note: ritm.getValue('number') + ': ' + ritm.variables.justification};

        const records = [asset];
        if (!asset.ci.nil()) {
            const ci = new GlideRecord('cmdb_ci');
            if (ci.get(asset.getValue('ci')) && ci.isValidField(change.field)) records.push(ci);
        }
        if (records.every(function (r) { return r.getValue(change.field) === value; })) {
            this._close(ritm, ItamKitRequests.RITM_CLOSED_COMPLETE, 'Nothing to change: the ' + change.label + ' was already set.');
            return ItamKitResult.ok(208, asset.getDisplayValue() + ' already has this ' + change.label);
        }
        let changes = 0;
        const names = [];
        records.forEach(function (record) {
            const old = record.getValue(change.field);
            if (old === value) return;
            record.setValue(change.field, value);
            record.update();
            changes += ItamKitAudit.logChanges(Object.assign({table: record.getValue('sys_class_name'), id: record.getUniqueValue(),
                display: record.getDisplayValue()}, base), {[change.field]: old}, {[change.field]: value});
            names.push(record.getDisplayValue());
        });
        const shown = records[0].getElement(change.field).getDisplayValue();
        this._close(ritm, ItamKitRequests.RITM_CLOSED_COMPLETE, 'Changed ' + change.label + ' to ' + shown + ' on ' + names.join(' and ') + '.');
        return ItamKitResult.ok(200, change.label + ' set to ' + shown + ' on ' + names.join(' and ') + ' (' + changes + ' audit row(s))',
            {changed: names, audit_rows: changes});
    },

    /** After a rejection: nothing changes; the requested item is closed incomplete with the approver's comment. */
    reject: function (ritm) {
        const approval = new GlideRecord('sysapproval_approver');
        approval.addQuery('sysapproval', ritm.getUniqueValue());
        approval.addQuery('state', 'rejected');
        approval.orderByDesc('sys_updated_on');
        approval.setLimit(1);
        approval.query();
        const comment = approval.next() ? approval.comments.getJournalEntry(1).replace(/^.*\n/, '').trim() : '';
        this._close(ritm, ItamKitRequests.RITM_CLOSED_INCOMPLETE, 'Rejected, nothing was changed.' + (comment ? ' Reason: ' + comment : ''));
        return ItamKitResult.ok(200, ritm.getValue('number') + ' rejected; nothing changed' + (comment ? ' (reason: ' + comment + ')' : ''),
            {reason: comment});
    },

    // ------------------------------------------------------------------ helpers

    _isChange: function (ritm) {
        return ritm.cat_item.name.toString() === 'Asset-Daten oder Standort ändern';
    },

    _asset: function (id) {
        const asset = new GlideRecord('alm_hardware');
        return id && asset.get(id) ? asset : null;
    },

    _activeUser: function (element) {
        return !element.nil() && ItamKitConfig.isTrue(element.active);
    },

    _tasks: function (ritm) {
        const found = {return_task: '', replacement_task: ''};
        const task = new GlideRecord('asset_task');
        task.addQuery('parent', ritm.getUniqueValue());
        task.query();
        while (task.next()) {
            if (task.getValue('task_name') === 'Device return') found.return_task = task.getUniqueValue();
            if (task.getValue('task_name') === 'Device replacement') found.replacement_task = task.getUniqueValue();
        }
        return found;
    },

    _newTask: function (ritm, asset, name, description, model) {
        const task = new GlideRecord('asset_task');
        task.initialize();
        task.setValue('parent', ritm.getUniqueValue());
        task.setValue('task_name', name);
        task.setValue('short_description', description);
        task.setValue('requested_for', ritm.variables.requested_for.toString() || ritm.getValue('requested_for'));
        if (asset) {
            task.setValue('asset', asset.getUniqueValue());
            task.setValue('model', asset.getValue('model'));
        } else if (model) {
            task.setValue('model', model);
        }
        if (ritm.getValue('assignment_group')) task.setValue('assignment_group', ritm.getValue('assignment_group'));
        return task.insert();
    },

    _close: function (ritm, state, note) {
        ritm.setValue('state', state);
        ritm.work_notes = note;
        ritm.update();
    },

    type: 'ItamKitRequests'
};
