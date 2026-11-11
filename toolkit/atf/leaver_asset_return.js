/**
 * ATF test «ITAM Toolkit: leaver asset return», step «Run Server Side Script» (Jasmine 3.1).
 * Module 1: triggers (a) API/producer path, (b) deactivation, (c) nightly sweep; the four end
 * states; idempotency; reminders and escalation; KPIs. The test creates its own users and
 * devices; ATF rolls all changes back after the run.
 */
(function (outputs, steps, params, stepResult, assertEqual) {
    const resolver = new LeaverAssetResolver();
    const CASE = ItamKitConfig.table('leaver_case');
    const OUTCOME = ItamKitConfig.outcomeField();
    const stamp = String(new GlideDateTime().getNumericValue());

    function newUser(name, managerId, inactive) {
        const user = new GlideRecord('sys_user');
        user.initialize();
        user.setValue('user_name', 'atf.itamkit.' + name + '.' + stamp);
        user.setValue('first_name', 'ATF');
        user.setValue('last_name', name);
        user.setValue('email', 'atf.' + name + '@example.com');
        if (managerId) user.setValue('manager', managerId);
        if (inactive) user.setValue('active', false);
        return user.insert();
    }

    function newDevice(name, userId) {
        const ci = new GlideRecord('cmdb_ci_computer');
        ci.initialize();
        ci.setValue('name', 'ATF-' + name + '-' + stamp);
        ci.setValue('install_status', '1');
        ci.setValue('assigned_to', userId);
        const ciId = ci.insert();
        // The platform rule «Create Asset on insert» may already have created the asset.
        const asset = new GlideRecord('alm_hardware');
        if (!asset.get('ci', ciId)) {
            asset.initialize();
            asset.setValue('ci', ciId);
        }
        asset.setValue('asset_tag', 'ATF-' + name + '-' + stamp);
        asset.setValue('install_status', '1');
        asset.setValue('assigned_to', userId);
        return asset.isNewRecord() ? asset.insert() : (asset.update(), asset.getUniqueValue());
    }

    function load(table, id) {
        const gr = new GlideRecord(table);
        gr.get(id);
        return gr;
    }

    function tasksOf(caseId) {
        const ids = [];
        const task = new GlideRecord('asset_task');
        task.addQuery('parent', caseId);
        task.orderBy('number');
        task.query();
        while (task.next()) ids.push(task.getUniqueValue());
        return ids;
    }

    function daysAgo(n) {
        const d = new GlideDateTime();
        d.addDaysLocalTime(-n);
        return d.getLocalDate().getValue();
    }

    describe('resolve() (API / record producer path)', function () {
        it('opens one case with one return task per assigned device and is idempotent', function () {
            const boss = newUser('boss');
            const hr = newUser('hr');
            const leaver = newUser('leaver1', boss);
            newDevice('NB1', leaver);
            newDevice('NB2', leaver);
            newDevice('PH1', leaver);
            newDevice('OTHER', newUser('colleague'));

            const first = resolver.resolve(leaver, 'manual', {lastWorkingDay: daysAgo(1), hrContact: hr});
            expect(first.success).toBe(true);
            expect(first.status_code).toBe(201);
            expect(first.data.tasks_total).toBe(3);
            const leaverCase = load(CASE, first.data.case_id);
            expect(leaverCase.getValue('leaver')).toBe(leaver);
            expect(leaverCase.getValue('manager')).toBe(boss);
            expect(leaverCase.getValue('hr_contact')).toBe(hr);
            expect(ItamKitConfig.isTrue(leaverCase.lwd_estimated)).toBe(false);

            const due = leaverCase.getValue('due_date');
            const later = resolver.resolve(leaver, 'manual', {lastWorkingDay: daysAgo(0)});
            expect(later.status_code).toBe(208);
            expect(load(CASE, first.data.case_id).getValue('due_date')).not.toBe(due);
            const task = new GlideRecord('asset_task');
            task.addQuery('parent', first.data.case_id);
            task.query();
            task.next();
            expect(task.getValue('due_date')).toBe(load(CASE, first.data.case_id).getValue('due_date'));

            const second = resolver.resolve(leaver, 'manual');
            expect(second.status_code).toBe(208);
            expect(second.data.case_id).toBe(first.data.case_id);
            expect(tasksOf(first.data.case_id).length).toBe(3);
        });

        it('answers 204 for a user without hardware and 404 for an unknown user', function () {
            expect(resolver.resolve(newUser('nohardware'), 'manual').status_code).toBe(204);
            expect(resolver.resolve('0123456789abcdef0123456789abcdef', 'manual').status_code).toBe(404);
        });
    });

    describe('completeReturn(): end states and KPIs', function () {
        it('sets In stock / Pending repair / Pending disposal / Missing and closes the case', function () {
            const leaver = newUser('leaver2');
            const assets = [newDevice('R1', leaver), newDevice('R2', leaver), newDevice('R3', leaver), newDevice('R4', leaver)];
            const lastDay = daysAgo(2);
            const opened = resolver.resolve(leaver, 'manual', {lastWorkingDay: lastDay});
            const tasks = tasksOf(opened.data.case_id);
            expect(tasks.length).toBe(4);

            const outcomes = ['in_stock', 'pending_repair', 'pending_disposal', 'missing_lost'];
            tasks.forEach(function (taskId, i) {
                const result = resolver.completeReturn(taskId, outcomes[i]);
                expect(result.success).toBe(true);
                expect(result.status_code).toBe(200);
            });

            const byTask = {};
            tasks.forEach(function (taskId) {
                const task = load('asset_task', taskId);
                byTask[task.getValue(OUTCOME)] = load('alm_hardware', task.getValue('asset'));
            });
            expect(byTask.in_stock.getValue('install_status')).toBe('6');
            expect(byTask.in_stock.getValue('substatus')).toBe('available');
            expect(byTask.in_stock.assigned_to.nil()).toBe(true);
            expect(byTask.pending_repair.getValue('substatus')).toBe('pending_repair');
            expect(byTask.pending_disposal.getValue('substatus')).toBe('pending_disposal');
            expect(byTask.missing_lost.getValue('install_status')).toBe('8');
            expect(byTask.missing_lost.getValue('substatus')).toBe('lost');
            expect(byTask.missing_lost.getValue('assigned_to')).toBe(leaver);

            const leaverCase = load(CASE, opened.data.case_id);
            expect(ItamKitConfig.isTrue(leaverCase.active)).toBe(false);
            expect(leaverCase.getValue('state')).toBe('4');
            expect(leaverCase.getValue('assets_returned')).toBe('3');
            expect(leaverCase.getValue('assets_lost')).toBe('1');
            expect(parseFloat(leaverCase.getValue('return_rate'))).toBe(75);
            expect(parseInt(leaverCase.getValue('cycle_time_days'), 10)).toBe(2);

            const audit = new GlideRecord(ItamKitConfig.table('audit_log'));
            audit.addQuery('target_id', 'IN', assets.join(','));
            audit.addQuery('module', 'leaver');
            audit.query();
            expect(audit.getRowCount()).toBeGreaterThan(3);

            const kpi = resolver.kpis('sys_id=' + opened.data.case_id);
            expect(kpi.data.cases_closed).toBe(1);
            expect(kpi.data.return_rate).toBe(75);
            expect(kpi.data.avg_cycle_days).toBe(2);
        });

        it('is idempotent and validates the outcome', function () {
            const leaver = newUser('leaver3');
            newDevice('V1', leaver);
            const opened = resolver.resolve(leaver, 'manual');
            const taskId = tasksOf(opened.data.case_id)[0];
            expect(resolver.completeReturn(taskId, 'sold').status_code).toBe(400);
            expect(resolver.completeReturn(taskId, 'in_stock').status_code).toBe(200);
            expect(resolver.completeReturn(taskId, 'in_stock').status_code).toBe(208);
            expect(resolver.completeReturn(taskId, 'missing_lost').status_code).toBe(409);
        });
    });

    describe('triggers (b) deactivation and (c) nightly sweep', function () {
        it('opens a case when the user is deactivated', function () {
            const leaver = newUser('leaver4');
            newDevice('D1', leaver);
            const user = load('sys_user', leaver);
            user.setValue('active', false);
            user.update();
            const leaverCase = resolver.findOpenCase(leaver);
            expect(leaverCase).not.toBeNull();
            expect(leaverCase.getValue('trigger_source')).toBe('user_deactivated');
            expect(ItamKitConfig.isTrue(leaverCase.lwd_estimated)).toBe(true);
            expect(tasksOf(leaverCase.getUniqueValue()).length).toBe(1);
        });

        it('catches a leaver whose deactivation never fired the trigger (e.g. loaded inactive by an import)', function () {
            // Scoped apps may not call setWorkflow(false) on sys_user; a user inserted as inactive
            // bypasses the «active changes to false» trigger in the same way.
            const leaver = newUser('leaver5', '', true);
            newDevice('S1', leaver);
            expect(resolver.findOpenCase(leaver)).toBeNull();

            const sweep = resolver.sweep({userId: leaver, caseQuery: 'leaver=' + leaver});
            expect(sweep.success).toBe(true);
            expect(sweep.data.cases_opened.length).toBe(1);
            const leaverCase = resolver.findOpenCase(leaver);
            expect(leaverCase.getValue('trigger_source')).toBe('nightly_sweep');
            expect(resolver.sweep({userId: leaver, caseQuery: 'leaver=' + leaver}).data.cases_opened.length).toBe(0);
        });
    });

    describe('reminders on day 3 / 7 / 14', function () {
        it('reminds manager and HR, then escalates to the manager\'s manager', function () {
            const director = newUser('director');
            const boss = newUser('boss2', director);
            const hr = newUser('hr2');
            const leaver = newUser('leaver6', boss);
            newDevice('M1', leaver);
            const opened = resolver.resolve(leaver, 'manual', {lastWorkingDay: daysAgo(8), hrContact: hr});
            const caseId = opened.data.case_id;
            const onlyThisCase = 'sys_id=' + caseId;

            const first = resolver.sendDueReminders(onlyThisCase);
            expect(first.data.sent).toBe(1);
            expect(first.data.escalations).toBe(0);
            let leaverCase = load(CASE, caseId);
            expect(leaverCase.getValue('reminder_level')).toBe('7');
            expect(ItamKitConfig.isTrue(leaverCase.escalated)).toBe(false);
            const reminder = first.data.details[0];
            expect(reminder.day).toBe(7);
            expect(reminder.recipients).toContain(boss);
            expect(reminder.recipients).toContain(hr);
            expect(reminder.recipients).not.toContain(director);
            expect(reminder.recipients).not.toContain(leaver);

            expect(resolver.sendDueReminders(onlyThisCase).data.sent).toBe(0);

            leaverCase.setValue('last_working_day', daysAgo(15));
            leaverCase.update();
            const second = resolver.sendDueReminders(onlyThisCase);
            expect(second.data.escalations).toBe(1);
            leaverCase = load(CASE, caseId);
            expect(leaverCase.getValue('reminder_level')).toBe('14');
            expect(ItamKitConfig.isTrue(leaverCase.escalated)).toBe(true);
            expect(leaverCase.getValue('priority')).toBe('2');
            expect(second.data.details[0].escalation).toBe(true);
            expect(second.data.details[0].recipients).toContain(director);
            expect(second.data.details[0].recipients).toContain(boss);
        });
    });

    describe('configuration guard', function () {
        it('rejects queries with unknown fields instead of ignoring them silently', function () {
            expect(ItamKitQuery.problems('alm_hardware', 'install_statusNOT IN6,7,8').length).toBe(0);
            expect(ItamKitQuery.problems('alm_hardware', 'assigned_to.active=false').length).toBe(0);
            expect(ItamKitQuery.problems('alm_hardware', 'assigned_to.actve=false').length).toBe(1);
            expect(ItamKitQuery.problems('alm_hardware', 'install_status=1^NQactive=true').length).toBeGreaterThan(0);
        });
    });
})(outputs, steps, params, stepResult, assertEqual);

jasmine.getEnv().execute();
