/**
 * ATF test «ITAM Toolkit: Gerät zurückgeben oder tauschen», step «Run Server Side Script» (Jasmine 3.1).
 * Flow «Gerät zurückgeben oder tauschen»: the flow asks the manager (or the fallback group) for the
 * approval; after the approval a return task and, for a defective device, a replacement task; closing
 * the return task sets the OOTB end state, keeps the CI consistent and writes the audit log; a
 * rejection changes nothing. ATF rolls all changes back after the run.
 */
(function (outputs, steps, params, stepResult, assertEqual) {
    // @helpers
    const ITEM = 'Gerät zurückgeben oder tauschen';

    describe('catalog item and flow', function () {
        it('is active and bound to a published flow', function () {
            const item = catalogItem(ITEM);
            expect(item.isValidRecord()).toBe(true);
            expect(ItamKitConfig.isTrue(item.active)).toBe(true);
            expect(item.flow_designer_flow.nil()).toBe(false);
            expect(item.flow_designer_flow.status.toString()).toBe('published');
        });
    });

    describe('happy path: manager approves, defective device', function () {
        it('routes the approval to the manager and processes the return', function () {
            const item = catalogItem(ITEM);
            const boss = newUser('boss');
            const user = newUser('worker', boss);
            const device = newDevice('NB1', {assigned_to: user});
            const ritm = newRequest(item, user, {requested_for: user, device: device.asset, reason: 'defekt', comment: 'Display broken'});

            const context = runFlowToApproval(item, ritm);
            expect(approvers(ritm)).toContain(boss);
            cancelFlow(context);

            const started = requests.run('start_return', ritm.getUniqueValue());
            expect(started.status_code).toBe(201);
            expect(started.data.replacement_task).not.toBe('');
            expect(requests.run('start_return', ritm.getUniqueValue()).status_code).toBe(208);

            expect(requests.run('complete_return', ritm.getUniqueValue()).status_code).toBe(409);
            const task = load('asset_task', started.data.return_task);
            task.setValue('state', '3');
            task.update();

            const done = requests.run('complete_return', ritm.getUniqueValue());
            expect(done.success).toBe(true);
            expect(done.status_code).toBe(200);
            const asset = load('alm_hardware', device.asset);
            expect(asset.getValue('install_status')).toBe('6');
            expect(asset.getValue('substatus')).toBe('pending_repair');
            expect(asset.assigned_to.nil()).toBe(true);
            expect(load('cmdb_ci', device.ci).getValue('install_status')).toBe(new AssetCiDrift().expectedCiStatus('6', 'pending_repair'));
            expect(auditRows(device.asset)).toBeGreaterThan(0);
            expect(load('sc_req_item', ritm.getUniqueValue()).getValue('state')).toBe('3');
        });
    });

    describe('fallback group and rejection', function () {
        it('asks the fallback group when the user has no manager, and a rejection changes nothing', function () {
            const item = catalogItem(ITEM);
            const user = newUser('nomanager');
            const device = newDevice('NB2', {assigned_to: user});
            const ritm = newRequest(item, user, {requested_for: user, device: device.asset, reason: 'nicht_benoetigt'});

            const who = requests.run('approver', ritm.getUniqueValue());
            expect(who.data.approver_user).toBe('');
            expect(who.data.approver_group).not.toBe('');
            const context = runFlowToApproval(item, ritm);
            const members = groupMembers(ItamKitConfig.prop('requests.fallback_group', ''));
            expect(members.length).toBeGreaterThan(0);
            expect(approvers(ritm)).toContain(members[0]);
            cancelFlow(context);

            rejectWith(ritm, members[0], 'Gerät wird noch gebraucht');
            const rejected = requests.run('reject', ritm.getUniqueValue());
            expect(rejected.status_code).toBe(200);
            expect(rejected.data.reason).toContain('noch gebraucht');
            expect(load('sc_req_item', ritm.getUniqueValue()).getValue('state')).toBe('4');
            const asset = load('alm_hardware', device.asset);
            expect(asset.getValue('install_status')).toBe('1');
            expect(asset.getValue('assigned_to')).toBe(user);
        });
    });

    describe('validation', function () {
        it('rejects a device of somebody else, unknown steps and unknown requests', function () {
            const item = catalogItem(ITEM);
            const user = newUser('requester');
            const other = newUser('other');
            const device = newDevice('NB3', {assigned_to: other});
            const ritm = newRequest(item, user, {requested_for: user, device: device.asset, reason: 'tausch'});
            expect(requests.run('start_return', ritm.getUniqueValue()).status_code).toBe(409);
            expect(requests.run('dance', ritm.getUniqueValue()).status_code).toBe(400);
            expect(requests.run('approver', '0123456789abcdef0123456789abcdef').status_code).toBe(404);
        });
    });
})(outputs, steps, params, stepResult, assertEqual);

jasmine.getEnv().execute();
