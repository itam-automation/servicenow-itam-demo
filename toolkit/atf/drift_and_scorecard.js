/**
 * ATF test «ITAM Toolkit: asset/CI drift and DQ scorecard», step «Run Server Side Script» (Jasmine 3.1).
 * Module 2: target state from the OOTB mapping, scan, fix with either leading side, audit log,
 * rule types of the scorecard, invalid rules, weighted score. The test creates its own company,
 * devices and rules; ATF rolls all changes back after the run.
 */
(function (outputs, steps, params, stepResult, assertEqual) {
    const stamp = String(new GlideDateTime().getNumericValue());
    const FINDING = ItamKitConfig.table('drift_finding');
    const RULE = ItamKitConfig.table('dq_rule');

    function insert(table, values) {
        const gr = new GlideRecord(table);
        gr.initialize();
        Object.keys(values).forEach(function (k) {
            gr.setValue(k, values[k]);
        });
        return gr.insert();
    }

    function load(table, id) {
        const gr = new GlideRecord(table);
        gr.get(id);
        return gr;
    }

    function newCompany(name) {
        return insert('core_company', {name: 'ATF ' + name + ' ' + stamp});
    }

    /** CI and asset in use; returns {ci, asset}. The platform may create the asset itself («Create Asset on insert»). */
    function newPair(name, companyId, extra) {
        const ci = insert('cmdb_ci_computer', Object.assign({name: 'ATF-' + name + '-' + stamp, install_status: '1', company: companyId}, extra || {}));
        const asset = new GlideRecord('alm_hardware');
        if (!asset.get('ci', ci)) {
            asset.initialize();
            asset.setValue('ci', ci);
        }
        asset.setValue('install_status', '1');
        asset.setValue('company', companyId);
        asset.setValue('asset_tag', 'ATF-' + name + '-' + stamp);
        const assetId = asset.isNewRecord() ? asset.insert() : (asset.update(), asset.getUniqueValue());
        return {ci: ci, asset: assetId};
    }

    /** Changes the CI status the way an integration would (scoped apps may not use setWorkflow(false) on cmdb_ci). */
    function forceCiStatus(ciId, status) {
        const ci = load('cmdb_ci', ciId);
        ci.setValue('install_status', status);
        ci.update();
    }

    function openFinding(assetId) {
        const finding = new GlideRecord(FINDING);
        finding.addQuery('asset', assetId);
        finding.addQuery('state', 'open');
        finding.query();
        return finding.next() ? finding : null;
    }

    function rule(values) {
        const gr = new GlideRecord(RULE);
        gr.initialize();
        gr.setValue('company_field', 'company');
        gr.setValue('weight', 1);
        Object.keys(values).forEach(function (k) {
            gr.setValue(k, values[k]);
        });
        return gr;
    }

    describe('target state: OOTB asset/CI status mapping', function () {
        it('maps asset states to CI states and back', function () {
            const drift = new AssetCiDrift();
            expect(drift.expectedCiStatus('1', '')).toBe('1');
            expect(drift.expectedCiStatus('6', 'available')).toBe('6');
            expect(drift.expectedCiStatus('6', 'pending_repair')).toBe('5');
            expect(drift.expectedCiStatus('8', 'lost')).toBe('100');
            expect(drift.expectedAsset('5').substate).toBe('pending_repair');
            expect(drift.expectedAsset('7').state).toBe('7');
        });
    });

    describe('drift watcher', function () {
        it('finds drift and fixes it with the asset leading', function () {
            const company = newCompany('Drift A');
            const pair = newPair('DA1', company);
            newPair('DA2', company);
            forceCiStatus(pair.ci, '6');

            const scan = new AssetCiDrift().scan(company);
            expect(scan.success).toBe(true);
            expect(scan.data.population).toBe(2);
            expect(scan.data.created).toBe(1);
            const finding = openFinding(pair.asset);
            expect(finding.getValue('ci_status')).toBe('6');
            expect(finding.getValue('expected_ci_status')).toBe('1');
            expect(finding.getValue('preview_asset_leads')).toContain('In Stock');
            expect(finding.getValue('preview_ci_leads')).toContain('Available');

            const fix = new AssetCiDrift().fix(finding.getUniqueValue(), 'asset');
            expect(fix.success).toBe(true);
            expect(fix.status_code).toBe(200);
            expect(load('cmdb_ci', pair.ci).getValue('install_status')).toBe('1');
            const fixed = load(FINDING, finding.getUniqueValue());
            expect(fixed.getValue('state')).toBe('fixed');
            expect(fixed.getValue('leading_side')).toBe('asset');

            const audit = new GlideRecord(ItamKitConfig.table('audit_log'));
            audit.addQuery('finding', finding.getUniqueValue());
            audit.addQuery('field', 'install_status');
            audit.query();
            expect(audit.next()).toBe(true);
            expect(audit.getValue('old_value')).toBe('6');
            expect(audit.getValue('new_value')).toBe('1');

            expect(new AssetCiDrift().scan(company).data.drifting).toBe(0);
        });

        it('fixes drift with the CI leading', function () {
            const company = newCompany('Drift B');
            const pair = newPair('DB1', company);
            forceCiStatus(pair.ci, '7');
            new AssetCiDrift().scan(company);
            const finding = openFinding(pair.asset);
            const fix = new AssetCiDrift().fix(finding.getUniqueValue(), 'ci');
            expect(fix.success).toBe(true);
            expect(load('alm_hardware', pair.asset).getValue('install_status')).toBe('7');
            expect(new AssetCiDrift().count(company).data.defects).toBe(0);
        });

        it('validates the input and is idempotent', function () {
            const company = newCompany('Drift C');
            const pair = newPair('DC1', company);
            forceCiStatus(pair.ci, '6');
            new AssetCiDrift().scan(company);
            const findingId = openFinding(pair.asset).getUniqueValue();
            expect(new AssetCiDrift().fix(findingId, 'sideways').status_code).toBe(400);
            expect(new AssetCiDrift().fix('0123456789abcdef0123456789abcdef', 'asset').status_code).toBe(404);
            expect(new AssetCiDrift().fix(findingId, 'asset').status_code).toBe(200);
            expect(new AssetCiDrift().fix(findingId, 'asset').status_code).toBe(208);
        });
    });

    describe('DQ scorecard', function () {
        it('evaluates the four rule types and rejects invalid rules', function () {
            const company = newCompany('Score');
            const maker = insert('core_company', {name: 'ATF Maker ' + stamp, manufacturer: true});
            const other = insert('core_company', {name: 'ATF Other ' + stamp, manufacturer: true});
            const model = insert('cmdb_hardware_product_model', {name: 'ATF Model ' + stamp, manufacturer: maker});
            newPair('S1', company, {serial_number: 'ATF-SN-1', model_id: model, manufacturer: maker});
            newPair('S2', company, {serial_number: 'ATF-SN-1', model_id: model, manufacturer: other});
            newPair('S3', company, {serial_number: 'ATF-SN-3', model_id: model, manufacturer: maker});
            const lonely = newPair('S4', company, {model_id: model, manufacturer: maker});
            forceCiStatus(lonely.ci, '6');

            const dq = new DqScorecard();
            const missing = dq.evaluate(rule({table_name: 'cmdb_ci_hardware', rule_type: 'query', defect_query: 'serial_numberISEMPTY'}), company);
            expect(missing.status).toBe('ok');
            expect(missing.population).toBe(4);
            expect(missing.defects).toBe(1);
            expect(missing.score).toBe(75);

            const duplicate = dq.evaluate(rule({table_name: 'cmdb_ci_hardware', rule_type: 'duplicate', field: 'serial_number'}), company);
            expect(duplicate.defects).toBe(1);

            const mismatch = dq.evaluate(rule({table_name: 'cmdb_ci_hardware', rule_type: 'field_mismatch',
                field: 'manufacturer', compare_field: 'model_id.manufacturer'}), company);
            expect(mismatch.defects).toBe(1);

            const drift = dq.evaluate(rule({table_name: 'alm_hardware', rule_type: 'drift'}), company);
            expect(drift.population).toBe(4);
            expect(drift.defects).toBe(1);

            const typo = dq.evaluate(rule({table_name: 'cmdb_ci_hardware', rule_type: 'query', defect_query: 'serial_numbr=X'}), company);
            expect(typo.status).toBe('invalid');
            expect(typo.message).toContain('serial_numbr');

            const empty = dq.evaluate(rule({table_name: 'cmdb_ci_hardware', rule_type: 'query', population_query: 'install_status=8',
                defect_query: 'serial_numberISEMPTY'}), company);
            expect(empty.status).toBe('empty');
        });

        it('stores a snapshot whose score is the weighted mean of the rule scores', function () {
            const company = newCompany('Snapshot');
            newPair('P1', company, {serial_number: 'ATF-P-1'});
            newPair('P2', company);
            const card = insert(ItamKitConfig.table('dq_scorecard'), {name: 'ATF ' + stamp, company: company, active: true});
            const run = new DqScorecard().run(card, 'manual');
            expect(run.success).toBe(true);
            expect(run.status_code).toBe(201);

            let weighted = 0;
            let weights = 0;
            run.data.rules.forEach(function (r) {
                if (r.status !== 'ok') return;
                weighted += r.weight * (100 * (1 - r.defects / r.population));
                weights += r.weight;
            });
            expect(run.data.score).toBe(Math.round(100 * weighted / weights) / 100);
            const snapshot = load(ItamKitConfig.table('dq_snapshot'), run.data.snapshot_id);
            expect(parseFloat(snapshot.getValue('score'))).toBe(run.data.score);

            const latest = new DqScorecard().latest(card);
            expect(latest.data.results.length).toBe(run.data.rules.length);
        });
    });
})(outputs, steps, params, stepResult, assertEqual);

jasmine.getEnv().execute();
