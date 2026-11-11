/**
 * ATF test «ITAM Toolkit: Asset-Daten oder Standort ändern», step «Run Server Side Script» (Jasmine 3.1).
 * Flow «Asset-Daten oder Standort ändern»: the flow asks the asset owner, else the head of the asset's
 * department, else the fallback group; after the approval the new value is written to the asset and its
 * CI with old and new value in the audit log; a rejection changes nothing. ATF rolls all changes back.
 */
(function (outputs, steps, params, stepResult, assertEqual) {
    // @helpers
    const ITEM = 'Asset-Daten oder Standort ändern';

    function otherLocation(current) {
        return insert('cmn_location', {name: 'ATF Standort ' + stamp + (current ? ' 2' : '')});
    }

    describe('catalog item and flow', function () {
        it('is active and bound to a published flow', function () {
            const item = catalogItem(ITEM);
            expect(item.isValidRecord()).toBe(true);
            expect(ItamKitConfig.isTrue(item.active)).toBe(true);
            expect(item.flow_designer_flow.status.toString()).toBe('published');
        });
    });

    describe('happy path: asset owner approves a new location', function () {
        it('routes the approval to the owner and writes asset, CI and audit log', function () {
            const item = catalogItem(ITEM);
            const owner = newUser('owner');
            const oldLocation = otherLocation(false);
            const device = newDevice('CH1', {owned_by: owner, location: oldLocation});
            const newLocation = otherLocation(true);
            const ritm = newRequest(item, owner, {asset: device.asset, change_type: 'standort', new_location: newLocation,
                justification: 'Umzug in das neue Büro'});

            const context = runFlowToApproval(item, ritm);
            expect(approvers(ritm)).toContain(owner);
            cancelFlow(context);

            const applied = requests.run('apply_change', ritm.getUniqueValue());
            expect(applied.success).toBe(true);
            expect(applied.status_code).toBe(200);
            expect(load('alm_hardware', device.asset).getValue('location')).toBe(newLocation);
            expect(load('cmdb_ci', device.ci).getValue('location')).toBe(newLocation);
            expect(auditRows(device.asset)).toBe(1);
            expect(auditRows(device.ci)).toBeLessThan(2);
            expect(load('sc_req_item', ritm.getUniqueValue()).getValue('state')).toBe('3');
            expect(requests.run('apply_change', ritm.getUniqueValue()).status_code).toBe(208);
        });

        it('asks the head of the department when the asset has no owner', function () {
            const item = catalogItem(ITEM);
            const head = newUser('depthead');
            const department = insert('cmn_department', {name: 'ATF Abteilung ' + stamp, dept_head: head});
            const device = newDevice('CH2', {department: department});
            const ritm = newRequest(item, head, {asset: device.asset, change_type: 'standort', new_location: otherLocation(true),
                justification: 'Test'});
            const who = requests.run('approver', ritm.getUniqueValue());
            expect(who.data.approver_user).toBe(head);
            expect(who.data.source).toBe('head of the department');
        });
    });

    describe('fallback group and rejection', function () {
        it('asks the fallback group when nobody is responsible, and a rejection changes nothing', function () {
            const item = catalogItem(ITEM);
            const oldLocation = otherLocation(false);
            const device = newDevice('CH3', {location: oldLocation});
            const requester = newUser('requester');
            const ritm = newRequest(item, requester, {asset: device.asset, change_type: 'standort', new_location: otherLocation(true),
                justification: 'Bitte verschieben'});

            const context = runFlowToApproval(item, ritm);
            const members = groupMembers(ItamKitConfig.prop('requests.fallback_group', ''));
            expect(approvers(ritm)).toContain(members[0]);
            cancelFlow(context);

            rejectWith(ritm, members[0], 'Standort ist falsch angegeben');
            const rejected = requests.run('reject', ritm.getUniqueValue());
            expect(rejected.status_code).toBe(200);
            expect(load('sc_req_item', ritm.getUniqueValue()).getValue('state')).toBe('4');
            expect(load('alm_hardware', device.asset).getValue('location')).toBe(oldLocation);
            expect(auditRows(device.asset)).toBe(0);
        });
    });

    describe('validation', function () {
        it('rejects a request without the new value', function () {
            const item = catalogItem(ITEM);
            const device = newDevice('CH4', {});
            const ritm = newRequest(item, newUser('val'), {asset: device.asset, change_type: 'kostenstelle', justification: 'x'});
            expect(requests.run('apply_change', ritm.getUniqueValue()).status_code).toBe(400);
        });
    });
})(outputs, steps, params, stepResult, assertEqual);

jasmine.getEnv().execute();
