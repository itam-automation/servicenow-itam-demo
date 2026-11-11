/**
 * LeaverAssetResolver: asset return compliance for leavers on ServiceNow Core (no HAM Pro).
 *
 * One leaver case (<scope>_leaver_case, extends task) per leaver, one asset_task per
 * hardware asset that is still assigned to the leaver. Idempotent: calling it again
 * for the same leaver creates nothing new and answers 208.
 *
 * Entry points (all return the ItamKitResult contract {success, status_code, message, data}):
 *   resolve(userId, source, options)  open or reuse the case, create the missing return tasks
 *   syncTasks(caseGr)                 create missing return tasks, refresh counters, close when done
 *   completeReturn(taskId, outcome)   record one return: asset end state, task closed, case counters
 *   prepareReportedCase(current, producer)  record producer «Austritt melden» (HR)
 *   sweep(options)                    nightly: deactivations that bypassed the trigger, open cases, reminders
 *   sendDueReminders(caseQuery)       reminders on day 3, 7, 14 after the last working day (last = escalation)
 *   kpis(query)                       return rate and cycle time of closed cases (ISO 27001 A.5.11 evidence)
 */
var LeaverAssetResolver = Class.create();

/** End states of a return, checked against the OOTB choices of alm_asset.install_status/substatus. */
LeaverAssetResolver.OUTCOMES = {
    in_stock: {state: '6', substatus: 'available', returned: true, label: 'Returned: in stock'},
    pending_repair: {state: '6', substatus: 'pending_repair', returned: true, label: 'Returned: pending repair'},
    pending_disposal: {state: '6', substatus: 'pending_disposal', returned: true, label: 'Returned: pending disposal'},
    missing_lost: {state: '8', substatus: 'lost', returned: false, label: 'Missing: lost'}
};

LeaverAssetResolver.TASK_CLOSED_COMPLETE = '3';
LeaverAssetResolver.TASK_CLOSED_INCOMPLETE = '4';
LeaverAssetResolver.PRIORITY_HIGH = '2';

/** Form buttons on asset_task call this with their outcome. */
LeaverAssetResolver.uiComplete = function (current, outcome) {
    const result = new LeaverAssetResolver().completeReturn(current.getUniqueValue(), outcome);
    if (result.success) {
        gs.addInfoMessage(result.message);
    } else {
        gs.addErrorMessage(result.message);
    }
    return result;
};

LeaverAssetResolver.prototype = {
    initialize: function () {
        this.caseTable = ItamKitConfig.table('leaver_case');
        this.outcomeField = ItamKitConfig.outcomeField();
        this.assetQuery = ItamKitConfig.prop('leaver.asset_query', 'install_statusNOT IN6,7,8');
        this.assignmentGroup = ItamKitConfig.prop('leaver.assignment_group', '');
        this.reminderDays = String(ItamKitConfig.prop('leaver.reminder_days', '3,7,14')).split(',')
            .map(function (d) { return parseInt(d, 10); })
            .filter(function (d) { return d > 0; })
            .sort(function (a, b) { return a - b; });
    },

    // ----------------------------------------------------------------- triggers

    /**
     * Opens (or reuses) the leaver case of a user and creates one return task per assigned asset.
     * source: record_producer | user_deactivated | nightly_sweep | manual
     * options: {lastWorkingDay: 'yyyy-MM-dd', hrContact: sys_id, privateEmail: string}
     */
    resolve: function (userId, source, options) {
        options = options || {};
        try {
            const invalid = this._invalidAssetQuery();
            if (invalid) return invalid;
            const user = new GlideRecord('sys_user');
            if (!userId || !user.get(userId)) return ItamKitResult.fail(404, 'User not found: ' + userId);
            const name = user.getDisplayValue();

            let leaverCase = this.findOpenCase(userId);
            let created = false;
            if (!leaverCase) {
                if (!this._assignedAssets(userId).length) {
                    return ItamKitResult.ok(204, name + ' has no assigned hardware; no case opened', {user: userId});
                }
                leaverCase = this._createCase(user, source, options);
                created = true;
            } else if (options.lastWorkingDay && leaverCase.getValue('last_working_day') !== options.lastWorkingDay) {
                leaverCase.setValue('last_working_day', options.lastWorkingDay);
                leaverCase.setValue('lwd_estimated', false);
                leaverCase.update();
            }

            const sync = this.syncTasks(leaverCase);
            if (!sync.success) return sync;
            const data = Object.assign({case_id: leaverCase.getUniqueValue(), case_number: leaverCase.getValue('number')}, sync.data);
            if (created) {
                return ItamKitResult.ok(201, data.case_number + ' opened for ' + name + ' with ' + data.tasks_total + ' return task(s)', data);
            }
            if (data.tasks_created) {
                return ItamKitResult.ok(200, data.case_number + ': ' + data.tasks_created + ' return task(s) added for ' + name, data);
            }
            return ItamKitResult.ok(208, data.case_number + ' already covers all ' + data.tasks_total + ' asset(s) of ' + name, data);
        } catch (e) {
            return ItamKitResult.fromError(e, 'LeaverAssetResolver.resolve');
        }
    },

    /**
     * Record producer «Austritt melden»: fills the new case from the variables.
     * Aborts the insert when the leaver already has an open case and updates that case instead.
     */
    prepareReportedCase: function (current, producer) {
        const userId = String(producer.leaver || '');
        const lastWorkingDay = String(producer.last_working_day || '');
        const privateEmail = String(producer.private_email || '');
        const user = new GlideRecord('sys_user');
        if (!userId || !user.get(userId)) {
            current.setAbortAction(true);
            return ItamKitResult.fail(400, 'Please select the leaver.');
        }
        const open = this.findOpenCase(userId);
        if (open) {
            open.setValue('last_working_day', lastWorkingDay);
            open.setValue('lwd_estimated', false);
            if (privateEmail) open.setValue('private_email', privateEmail);
            if (!open.getValue('hr_contact')) open.setValue('hr_contact', gs.getUserID());
            open.work_notes = 'HR reported the leaver again; last working day set to ' + lastWorkingDay + '.';
            open.update();
            current.setAbortAction(true);
            return ItamKitResult.ok(208, open.getValue('number') + ' is already open for ' + user.getDisplayValue() +
                '; last working day updated.', {case_id: open.getUniqueValue(), case_number: open.getValue('number')});
        }
        this._fillCase(current, user, 'record_producer', {
            lastWorkingDay: lastWorkingDay,
            hrContact: gs.getUserID(),
            privateEmail: privateEmail
        });
        return ItamKitResult.ok(201, 'Leaver case for ' + user.getDisplayValue() + ' created.');
    },

    // ------------------------------------------------------------- return tasks

    /** Creates the missing return tasks of a case, refreshes the counters and closes the case when done. */
    syncTasks: function (leaverCase) {
        try {
            const invalid = this._invalidAssetQuery();
            if (invalid) return invalid;
            const caseId = leaverCase.getUniqueValue();
            const userId = leaverCase.getValue('leaver');
            const covered = {};
            const tasks = new GlideRecord('asset_task');
            tasks.addQuery('parent', caseId);
            tasks.query();
            while (tasks.next()) covered[tasks.getValue('asset')] = true;

            let created = 0;
            const leaverName = leaverCase.leaver.getDisplayValue();
            this._assignedAssets(userId).forEach(function (asset) {
                if (covered[asset.sys_id]) return;
                const task = new GlideRecord('asset_task');
                task.initialize();
                task.setValue('parent', caseId);
                task.setValue('asset', asset.sys_id);
                task.setValue('requested_for', userId);
                task.setValue('model', asset.model);
                task.setValue('company', leaverCase.getValue('company'));
                task.setValue('task_name', 'Leaver asset return');
                task.setValue('short_description', 'Return ' + asset.display + ' (leaver ' + leaverName + ')');
                task.setValue('due_date', leaverCase.getValue('due_date'));
                if (leaverCase.getValue('assignment_group')) task.setValue('assignment_group', leaverCase.getValue('assignment_group'));
                task.insert();
                created++;
            });

            const counters = this._updateCounters(caseId);
            return ItamKitResult.ok(created ? 201 : 208, created + ' return task(s) created', Object.assign({tasks_created: created}, counters));
        } catch (e) {
            return ItamKitResult.fromError(e, 'LeaverAssetResolver.syncTasks');
        }
    },

    /**
     * Records the outcome of one return task.
     * outcome: in_stock | pending_repair | pending_disposal | missing_lost
     */
    completeReturn: function (taskId, outcome) {
        try {
            const spec = LeaverAssetResolver.OUTCOMES[outcome];
            if (!spec) {
                return ItamKitResult.fail(400, 'Unknown outcome "' + outcome + '"; use one of ' +
                    Object.keys(LeaverAssetResolver.OUTCOMES).join(', '));
            }
            const task = new GlideRecord('asset_task');
            if (!taskId || !task.get(taskId)) return ItamKitResult.fail(404, 'Return task not found: ' + taskId);
            if (!this.isLeaverTask(task)) return ItamKitResult.fail(409, task.getValue('number') + ' is not a leaver return task');
            if (!ItamKitConfig.isTrue(task.active)) {
                const recorded = task.getValue(this.outcomeField);
                if (recorded === outcome) {
                    return ItamKitResult.ok(208, task.getValue('number') + ' is already closed as ' + spec.label);
                }
                return ItamKitResult.fail(409, task.getValue('number') + ' is already closed with outcome "' + recorded + '"');
            }
            const asset = new GlideRecord('alm_hardware');
            if (!asset.get(task.getValue('asset'))) return ItamKitResult.fail(404, task.getValue('number') + ' has no hardware asset');

            const before = this._assetState(asset);
            asset.setValue('install_status', spec.state);
            asset.setValue('substatus', spec.substatus);
            if (spec.returned) {
                asset.setValue('assigned_to', '');
                if (task.getValue('stockroom')) asset.setValue('stockroom', task.getValue('stockroom'));
            }
            asset.update();
            asset.get(asset.getUniqueValue());
            const after = this._assetState(asset);
            ItamKitAudit.logChanges({
                module: 'leaver', action: 'return_' + outcome, table: 'alm_hardware',
                id: asset.getUniqueValue(), display: asset.getDisplayValue(),
                note: task.getValue('number') + ' (' + task.parent.getDisplayValue() + ')'
            }, before, after);

            task.setValue(this.outcomeField, outcome);
            task.setValue('state', spec.returned ? LeaverAssetResolver.TASK_CLOSED_COMPLETE : LeaverAssetResolver.TASK_CLOSED_INCOMPLETE);
            task.work_notes = spec.label + '. Asset ' + asset.getDisplayValue() + ': ' + asset.install_status.getDisplayValue() +
                (asset.getValue('substatus') ? ' / ' + asset.substatus.getDisplayValue() : '') + '.';
            task.update();

            const counters = this._updateCounters(task.getValue('parent'));
            return ItamKitResult.ok(200, task.getValue('number') + ': ' + spec.label + '; ' + asset.getDisplayValue() + ' is now ' +
                asset.install_status.getDisplayValue() + (asset.getValue('substatus') ? ' / ' + asset.substatus.getDisplayValue() : ''),
                Object.assign({task: task.getValue('number'), asset: asset.getDisplayValue(), outcome: outcome}, counters));
        } catch (e) {
            return ItamKitResult.fromError(e, 'LeaverAssetResolver.completeReturn');
        }
    },

    isLeaverTask: function (task) {
        return !task.parent.nil() && task.parent.sys_class_name.toString() === this.caseTable;
    },

    findOpenCase: function (userId) {
        const leaverCase = new GlideRecord(this.caseTable);
        leaverCase.addQuery('leaver', userId);
        leaverCase.addActiveQuery();
        leaverCase.orderBy('opened_at');
        leaverCase.setLimit(1);
        leaverCase.query();
        return leaverCase.next() ? leaverCase : null;
    },

    // ------------------------------------------------------------- nightly sweep

    /**
     * Nightly: (1) leavers whose deactivation bypassed the trigger (imports, LDAP, setWorkflow(false)),
     * (2) resync of all open cases (assets assigned after the report, cases without assets after the
     * last working day), (3) reminders.
     * options (optional, for partial runs and tests): {userId: only this user in step 1,
     * caseQuery: encoded query on the case table for steps 2 and 3}
     */
    sweep: function (options) {
        options = options || {};
        try {
            const invalid = this._invalidAssetQuery();
            if (invalid) return invalid;
            const opened = [];
            const leavers = new GlideAggregate('alm_hardware');
            leavers.addEncodedQuery(ItamKitQuery.and(this.assetQuery, 'assigned_to.active=false',
                options.userId ? 'assigned_to=' + options.userId : ''));
            leavers.groupBy('assigned_to');
            leavers.addAggregate('COUNT');
            leavers.query();
            while (leavers.next()) {
                const userId = leavers.getValue('assigned_to');
                if (this.findOpenCase(userId)) continue;
                const result = this.resolve(userId, 'nightly_sweep');
                if (result.status_code === 201) opened.push(result.data.case_number);
            }

            let tasksAdded = 0;
            let closed = 0;
            const open = new GlideRecord(this.caseTable);
            open.addActiveQuery();
            if (options.caseQuery) open.addEncodedQuery(options.caseQuery);
            open.query();
            while (open.next()) {
                const sync = this.syncTasks(open);
                if (sync.success) {
                    tasksAdded += sync.data.tasks_created;
                    if (sync.data.closed) closed++;
                }
            }
            const reminders = this.sendDueReminders(options.caseQuery);
            const data = {cases_opened: opened, tasks_added: tasksAdded, cases_closed: closed, reminders: reminders.data};
            return ItamKitResult.ok(200, 'Sweep: ' + opened.length + ' case(s) opened, ' + tasksAdded + ' task(s) added, ' +
                closed + ' case(s) closed, ' + reminders.data.sent + ' reminder(s), ' + reminders.data.escalations + ' escalation(s)', data);
        } catch (e) {
            return ItamKitResult.fromError(e, 'LeaverAssetResolver.sweep');
        }
    },

    /**
     * Reminders on the configured days after the last working day (default 3, 7, 14).
     * The leaver is inactive and receives no mail; the reminder goes to the manager, the
     * HR contact and the optional private address. The last day is the escalation: also
     * to the manager's manager (sys_user.manager), case priority high.
     */
    sendDueReminders: function (caseQuery) {
        const today = this._today();
        const escalationDay = this.reminderDays[this.reminderDays.length - 1];
        let sent = 0;
        let escalations = 0;
        const details = [];
        const leaverCase = new GlideRecord(this.caseTable);
        leaverCase.addActiveQuery();
        leaverCase.addNotNullQuery('last_working_day');
        if (caseQuery) leaverCase.addEncodedQuery(caseQuery);
        leaverCase.query();
        while (leaverCase.next()) {
            const overdue = this._daysBetween(leaverCase.getValue('last_working_day'), today);
            const due = this.reminderDays.filter(function (d) { return d <= overdue; }).pop();
            const level = parseInt(leaverCase.getValue('reminder_level') || '0', 10);
            if (!due || due <= level) continue;

            const escalation = due === escalationDay;
            const recipients = this._recipients(leaverCase, escalation);
            leaverCase.setValue('reminder_level', due);
            leaverCase.setValue('last_reminder', new GlideDateTime().getValue());
            if (escalation) {
                leaverCase.setValue('escalated', true);
                leaverCase.setValue('priority', LeaverAssetResolver.PRIORITY_HIGH);
            }
            leaverCase.work_notes = (escalation ? 'Escalation' : 'Reminder') + ' day ' + due + ' (' + overdue +
                ' days after the last working day) to: ' + (recipients.labels.join(', ') || 'nobody (no manager, no HR contact)');
            leaverCase.update();
            if (recipients.ids.length) {
                gs.eventQueue(ItamKitConfig.event(escalation ? 'leaver.escalation' : 'leaver.reminder'),
                    leaverCase, recipients.ids.join(','), String(due));
            }
            if (escalation) {
                escalations++;
            } else {
                sent++;
            }
            details.push({case_id: leaverCase.getUniqueValue(), case_number: leaverCase.getValue('number'), day: due,
                escalation: escalation, recipients: recipients.ids, recipient_names: recipients.labels});
        }
        return ItamKitResult.ok(200, sent + ' reminder(s), ' + escalations + ' escalation(s)',
            {sent: sent, escalations: escalations, details: details});
    },

    // ---------------------------------------------------------------------- KPIs

    /**
     * Return rate and cycle time of closed cases (optional extra encoded query on the case table).
     * return_rate = returned assets / assets of closed cases; cycle time = calendar days from the
     * last working day to the closure of the case; on time = closed by the escalation day.
     */
    kpis: function (query) {
        try {
            const target = this.reminderDays[this.reminderDays.length - 1];
            const k = {cases_closed: 0, cases_open: 0, assets_total: 0, assets_returned: 0, assets_lost: 0,
                return_rate: null, avg_cycle_days: null, max_cycle_days: null, on_time_rate: null, target_days: target};
            let cycleSum = 0;
            let onTime = 0;
            const leaverCase = new GlideRecord(this.caseTable);
            if (query) leaverCase.addEncodedQuery(query);
            leaverCase.query();
            while (leaverCase.next()) {
                if (ItamKitConfig.isTrue(leaverCase.active)) {
                    k.cases_open++;
                    continue;
                }
                k.cases_closed++;
                k.assets_total += parseInt(leaverCase.getValue('assets_total') || '0', 10);
                k.assets_returned += parseInt(leaverCase.getValue('assets_returned') || '0', 10);
                k.assets_lost += parseInt(leaverCase.getValue('assets_lost') || '0', 10);
                const cycle = parseInt(leaverCase.getValue('cycle_time_days') || '0', 10);
                cycleSum += cycle;
                k.max_cycle_days = Math.max(k.max_cycle_days || 0, cycle);
                if (cycle <= target) onTime++;
            }
            if (k.assets_total) k.return_rate = Math.round(10000 * k.assets_returned / k.assets_total) / 100;
            if (k.cases_closed) {
                k.avg_cycle_days = Math.round(10 * cycleSum / k.cases_closed) / 10;
                k.on_time_rate = Math.round(10000 * onTime / k.cases_closed) / 100;
            }
            return ItamKitResult.ok(200, k.cases_closed + ' closed case(s): return rate ' + k.return_rate + ' %, average cycle time ' +
                k.avg_cycle_days + ' day(s)', k);
        } catch (e) {
            return ItamKitResult.fromError(e, 'LeaverAssetResolver.kpis');
        }
    },

    // ------------------------------------------------------------------ helpers

    _createCase: function (user, source, options) {
        const leaverCase = new GlideRecord(this.caseTable);
        leaverCase.initialize();
        this._fillCase(leaverCase, user, source, options);
        leaverCase.insert();
        leaverCase.get(leaverCase.getUniqueValue());
        return leaverCase;
    },

    _fillCase: function (leaverCase, user, source, options) {
        const reported = !!options.lastWorkingDay;
        const lastWorkingDay = options.lastWorkingDay || this._today();
        leaverCase.setValue('leaver', user.getUniqueValue());
        leaverCase.setValue('trigger_source', source || 'manual');
        leaverCase.setValue('manager', user.getValue('manager'));
        leaverCase.setValue('company', user.getValue('company'));
        leaverCase.setValue('last_working_day', lastWorkingDay);
        leaverCase.setValue('lwd_estimated', !reported);
        leaverCase.setValue('due_date', lastWorkingDay + ' 23:59:59');
        if (options.hrContact) leaverCase.setValue('hr_contact', options.hrContact);
        if (options.privateEmail) leaverCase.setValue('private_email', options.privateEmail);
        if (this.assignmentGroup) leaverCase.setValue('assignment_group', this.assignmentGroup);
        leaverCase.setValue('short_description', 'Asset return for leaver ' + user.getDisplayValue());
    },

    _assignedAssets: function (userId) {
        const assets = [];
        const asset = new GlideRecord('alm_hardware');
        asset.addQuery('assigned_to', userId);
        asset.addEncodedQuery(this.assetQuery);
        asset.orderBy('asset_tag');
        asset.query();
        while (asset.next()) {
            assets.push({sys_id: asset.getUniqueValue(), display: asset.getDisplayValue(), model: asset.getValue('model')});
        }
        return assets;
    },

    _invalidAssetQuery: function () {
        const problems = ItamKitQuery.problems('alm_hardware', this.assetQuery);
        if (!problems.length) return null;
        return ItamKitResult.fail(422, 'Property leaver.asset_query is invalid: ' + problems.join('; '));
    },

    /** Recounts the tasks of a case; closes it when no task is open (and, without assets, after the last working day). */
    _updateCounters: function (caseId) {
        const counts = {total: 0, open: 0, returned: 0, lost: 0};
        const task = new GlideRecord('asset_task');
        task.addQuery('parent', caseId);
        task.query();
        while (task.next()) {
            counts.total++;
            if (ItamKitConfig.isTrue(task.active)) counts.open++;
            const outcome = LeaverAssetResolver.OUTCOMES[task.getValue(this.outcomeField)];
            if (outcome && outcome.returned) counts.returned++;
            if (outcome && !outcome.returned) counts.lost++;
        }
        const leaverCase = new GlideRecord(this.caseTable);
        leaverCase.get(caseId);
        leaverCase.setValue('assets_total', counts.total);
        leaverCase.setValue('assets_open', counts.open);
        leaverCase.setValue('assets_returned', counts.returned);
        leaverCase.setValue('assets_lost', counts.lost);
        leaverCase.setValue('return_rate', counts.total ? Math.round(10000 * counts.returned / counts.total) / 100 : '');

        const today = this._today();
        const afterLastDay = this._daysBetween(leaverCase.getValue('last_working_day') || today, today) > 0;
        let closed = false;
        if (ItamKitConfig.isTrue(leaverCase.active) && counts.open === 0 && (counts.total > 0 || afterLastDay)) {
            leaverCase.setValue('state', counts.lost ? LeaverAssetResolver.TASK_CLOSED_INCOMPLETE : LeaverAssetResolver.TASK_CLOSED_COMPLETE);
            leaverCase.setValue('cycle_time_days', Math.max(0, this._daysBetween(leaverCase.getValue('last_working_day') || today, today)));
            leaverCase.setValue('close_notes', counts.total ? counts.returned + ' of ' + counts.total + ' asset(s) returned, ' + counts.lost + ' missing/lost.'
                : 'No hardware was assigned to the leaver after the last working day.');
            closed = true;
        }
        leaverCase.update();
        return {tasks_total: counts.total, tasks_open: counts.open, assets_returned: counts.returned, assets_lost: counts.lost, closed: closed};
    },

    _recipients: function (leaverCase, escalation) {
        const ids = [];
        const labels = [];
        const add = function (element) {
            if (element.nil() || ids.indexOf(element.toString()) >= 0) return;
            if (!ItamKitConfig.isTrue(element.active)) {
                labels.push(element.getDisplayValue() + ' (inactive, skipped)');
                return;
            }
            ids.push(element.toString());
            labels.push(element.getDisplayValue());
        };
        add(leaverCase.manager.getRefRecord().isValidRecord() ? leaverCase.manager : leaverCase.leaver.manager);
        add(leaverCase.hr_contact);
        if (escalation) add(leaverCase.manager.manager);
        const privateEmail = leaverCase.getValue('private_email');
        if (privateEmail) {
            ids.push(privateEmail);
            labels.push('private address');
        }
        return {ids: ids, labels: labels};
    },

    _assetState: function (asset) {
        return {install_status: asset.getValue('install_status'), substatus: asset.getValue('substatus'),
            assigned_to: asset.getValue('assigned_to'), stockroom: asset.getValue('stockroom')};
    },

    _today: function () {
        return new GlideDateTime().getLocalDate().getValue();
    },

    /** Calendar days from date a to date b ('yyyy-MM-dd'), negative if b is earlier. */
    _daysBetween: function (a, b) {
        const parse = function (s) {
            const p = String(s).substring(0, 10).split('-');
            return Date.UTC(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
        };
        return Math.round((parse(b) - parse(a)) / 86400000);
    },

    type: 'LeaverAssetResolver'
};
