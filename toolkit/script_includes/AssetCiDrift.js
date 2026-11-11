/**
 * AssetCiDrift: watches whether a hardware asset and its CI tell the same lifecycle story.
 *
 * Target state = the platform's own table alm_asset_ci_state_mapping (Asset CI Install
 * Status Mapping, OOTB): asset install_status + substatus -> expected CI install_status.
 * Drift appears when updates bypass the platform's synchronisation (imports with business
 * rules off, setWorkflow(false), mapping entries that only sync asset -> CI).
 *
 *   scan(companyId)              one open finding per drifting asset (<scope>_drift_finding), with a preview
 *   fix(findingId, leadingSide)  'asset' or 'ci' leads; changes the other side, writes the audit log
 *   count(companyId)             population and drift count for the DQ scorecard
 * All entry points return the ItamKitResult contract.
 */
var AssetCiDrift = Class.create();

AssetCiDrift.OPEN = 'open';
AssetCiDrift.FIXED = 'fixed';
AssetCiDrift.RESOLVED = 'resolved';

AssetCiDrift.prototype = {
    initialize: function () {
        this.findingTable = ItamKitConfig.table('drift_finding');
        this.toCi = {};
        this.toAsset = {};
        this.labels = {};
        const map = new GlideRecord('alm_asset_ci_state_mapping');
        map.addActiveQuery();
        map.orderBy('asset_state');
        map.orderBy('asset_substate');
        map.query();
        while (map.next()) {
            const state = map.getValue('asset_state') || '';
            const substate = map.getValue('asset_substate') || '';
            const ci = map.getValue('configuration_item_status') || '';
            const direction = map.getValue('synch_direction') || '';
            this.toCi[state + '|' + substate] = {ci: ci, direction: direction};
            // Reverse direction (CI leads): only entries the platform itself syncs from the CI.
            if (ci && (direction === 'both' || direction === 'ci_to_asset') && !this.toAsset[ci]) {
                this.toAsset[ci] = {state: state, substate: substate};
            }
        }
    },

    /** Expected CI install_status for an asset state; null if the mapping sets no CI status. */
    expectedCiStatus: function (state, substate) {
        const entry = this.toCi[state + '|' + (substate || '')] || this.toCi[state + '|'];
        return entry && entry.ci ? entry.ci : null;
    },

    /** Asset state the platform derives from a CI status; null if there is no such mapping. */
    expectedAsset: function (ciStatus) {
        return this.toAsset[ciStatus] || null;
    },

    /** Population (assets with a CI) and drifting assets, for the DQ scorecard. */
    count: function (companyId) {
        let population = 0;
        let drift = 0;
        const asset = this._assets(companyId);
        while (asset.next()) {
            population++;
            if (this._drift(asset)) drift++;
        }
        return ItamKitResult.ok(200, drift + ' of ' + population + ' asset(s) drift from their CI', {population: population, defects: drift});
    },

    /** Creates or refreshes one open finding per drifting asset; closes findings that no longer drift. */
    scan: function (companyId) {
        try {
            const open = {};
            const finding = new GlideRecord(this.findingTable);
            finding.addQuery('state', AssetCiDrift.OPEN);
            if (companyId) finding.addQuery('company', companyId);
            finding.query();
            while (finding.next()) open[finding.getValue('asset')] = finding.getUniqueValue();

            let population = 0;
            let created = 0;
            let refreshed = 0;
            const asset = this._assets(companyId);
            while (asset.next()) {
                population++;
                const drift = this._drift(asset);
                const existing = open[asset.getUniqueValue()];
                delete open[asset.getUniqueValue()];
                if (!drift) {
                    if (existing) this._close(existing, AssetCiDrift.RESOLVED, 'No longer drifting at the scan.');
                    continue;
                }
                const record = new GlideRecord(this.findingTable);
                if (existing) {
                    record.get(existing);
                    refreshed++;
                } else {
                    record.initialize();
                    record.setValue('state', AssetCiDrift.OPEN);
                    created++;
                }
                this._fill(record, asset, drift);
                if (existing) {
                    record.update();
                } else {
                    record.insert();
                }
            }
            // Open findings whose asset left the population (CI removed, asset deleted)
            let closed = 0;
            Object.keys(open).forEach(function (assetId) {
                this._close(open[assetId], AssetCiDrift.RESOLVED, 'Asset no longer has a CI.');
                closed++;
            }, this);
            const total = created + refreshed;
            return ItamKitResult.ok(200, total + ' drifting asset(s) of ' + population + ' (' + created + ' new finding(s), ' + closed + ' closed)',
                {population: population, drifting: total, created: created, refreshed: refreshed, closed: closed});
        } catch (e) {
            return ItamKitResult.fromError(e, 'AssetCiDrift.scan');
        }
    },

    /**
     * Fixes one finding. leadingSide 'asset': the CI gets the status the mapping expects.
     * 'ci': the asset gets the state the platform derives from the CI status.
     */
    fix: function (findingId, leadingSide) {
        try {
            if (leadingSide !== 'asset' && leadingSide !== 'ci') {
                return ItamKitResult.fail(400, 'Choose the leading side: asset or ci');
            }
            const finding = new GlideRecord(this.findingTable);
            if (!findingId || !finding.get(findingId)) return ItamKitResult.fail(404, 'Drift finding not found: ' + findingId);
            if (finding.getValue('state') !== AssetCiDrift.OPEN) {
                return ItamKitResult.ok(208, finding.getDisplayValue() + ' is already ' + finding.getValue('state'));
            }
            const asset = new GlideRecord('alm_hardware');
            if (!asset.get(finding.getValue('asset'))) return ItamKitResult.fail(404, 'Asset of the finding no longer exists');
            const ci = new GlideRecord('cmdb_ci');
            if (!ci.get(asset.getValue('ci'))) return ItamKitResult.fail(409, asset.getDisplayValue() + ' no longer has a CI');

            const drift = this._drift(asset);
            if (!drift) {
                this._close(findingId, AssetCiDrift.RESOLVED, 'No longer drifting when the fix was requested.');
                return ItamKitResult.ok(208, asset.getDisplayValue() + ' no longer drifts; finding closed');
            }

            const before = {asset: this._assetSide(asset), ci: {install_status: ci.getValue('install_status')}};
            if (leadingSide === 'asset') {
                ci.setValue('install_status', drift.expectedCi);
                ci.update();
            } else {
                const target = this.expectedAsset(drift.ciStatus);
                if (!target) {
                    return ItamKitResult.fail(409, 'The platform maps no asset state to CI status ' + this._ciLabel(drift.ciStatus) +
                        '; let the asset lead instead');
                }
                asset.setValue('install_status', target.state);
                asset.setValue('substatus', target.substate);
                asset.update();
            }

            asset.get(asset.getUniqueValue());
            ci.get(ci.getUniqueValue());
            const after = {asset: this._assetSide(asset), ci: {install_status: ci.getValue('install_status')}};
            const base = {module: 'drift', action: 'fix_drift', leadingSide: leadingSide, finding: findingId};
            let changes = ItamKitAudit.logChanges(Object.assign({table: 'alm_hardware', id: asset.getUniqueValue(), display: asset.getDisplayValue()}, base),
                before.asset, after.asset);
            changes += ItamKitAudit.logChanges(Object.assign({table: ci.getValue('sys_class_name'), id: ci.getUniqueValue(), display: ci.getDisplayValue()}, base),
                before.ci, after.ci);

            const remaining = this._drift(asset);
            if (remaining) {
                return ItamKitResult.fail(409, 'Still drifting after the fix: asset ' + remaining.assetLabel + ', CI ' +
                    this._ciLabel(remaining.ciStatus) + ' (expected ' + this._ciLabel(remaining.expectedCi) + '). Check the platform rules.');
            }
            finding.setValue('state', AssetCiDrift.FIXED);
            finding.setValue('leading_side', leadingSide);
            finding.setValue('fixed_by', gs.getUserID());
            finding.setValue('fixed_on', new GlideDateTime().getValue());
            finding.setValue('resolution', (leadingSide === 'asset' ? 'Asset led' : 'CI led') + ': asset ' +
                this._assetLabel(after.asset.install_status, after.asset.substatus) + ', CI ' + this._ciLabel(after.ci.install_status) +
                ' (' + changes + ' field change(s) in the audit log).');
            finding.update();
            return ItamKitResult.ok(200, asset.getDisplayValue() + ': ' + finding.getValue('resolution'),
                {asset: after.asset, ci: after.ci, audit_rows: changes});
        } catch (e) {
            return ItamKitResult.fromError(e, 'AssetCiDrift.fix');
        }
    },

    // ------------------------------------------------------------------ helpers

    _assets: function (companyId) {
        const asset = new GlideRecord('alm_hardware');
        asset.addNotNullQuery('ci');
        if (companyId) asset.addQuery('company', companyId);
        asset.orderBy('asset_tag');
        asset.query();
        return asset;
    },

    /** Drift details of an asset, or null if asset and CI agree (or the mapping expects nothing). */
    _drift: function (asset) {
        const state = asset.getValue('install_status') || '';
        const substate = asset.getValue('substatus') || '';
        const expected = this.expectedCiStatus(state, substate);
        const ciStatus = asset.ci.install_status.toString();
        if (!expected || expected === ciStatus) return null;
        return {state: state, substate: substate, ciStatus: ciStatus, expectedCi: expected,
            assetLabel: this._assetLabel(state, substate)};
    },

    _fill: function (record, asset, drift) {
        const reverse = this.expectedAsset(drift.ciStatus);
        record.setValue('asset', asset.getUniqueValue());
        record.setValue('ci', asset.getValue('ci'));
        record.setValue('company', asset.getValue('company'));
        record.setValue('asset_state', drift.state);
        record.setValue('asset_substate', drift.substate);
        record.setValue('ci_status', drift.ciStatus);
        record.setValue('expected_ci_status', drift.expectedCi);
        record.setValue('proposed_asset_state', reverse ? reverse.state : '');
        record.setValue('proposed_asset_substate', reverse ? reverse.substate : '');
        record.setValue('preview_asset_leads', 'CI ' + asset.ci.getDisplayValue() + ': install status ' +
            this._ciLabel(drift.ciStatus) + ' -> ' + this._ciLabel(drift.expectedCi));
        record.setValue('preview_ci_leads', reverse ? 'Asset ' + asset.getDisplayValue() + ': ' + drift.assetLabel + ' -> ' +
            this._assetLabel(reverse.state, reverse.substate) : 'Not possible: the platform maps no asset state to CI status ' + this._ciLabel(drift.ciStatus));
        record.setValue('last_seen', new GlideDateTime().getValue());
        record.setValue('short_description', asset.getDisplayValue() + ': asset ' + drift.assetLabel + ', CI ' +
            this._ciLabel(drift.ciStatus) + ' (expected ' + this._ciLabel(drift.expectedCi) + ')');
    },

    _close: function (findingId, state, note) {
        const finding = new GlideRecord(this.findingTable);
        if (!finding.get(findingId)) return;
        finding.setValue('state', state);
        finding.setValue('resolution', note);
        finding.update();
    },

    _assetSide: function (asset) {
        return {install_status: asset.getValue('install_status'), substatus: asset.getValue('substatus')};
    },

    _assetLabel: function (state, substate) {
        const label = this._label('alm_asset', 'install_status', state);
        return substate ? label + ' / ' + this._label('alm_asset', 'substatus', substate) : label;
    },

    _ciLabel: function (status) {
        return this._label('cmdb_ci', 'install_status', status);
    },

    _label: function (table, element, value) {
        if (!value) return '(empty)';
        const key = table + '.' + element + '.' + value;
        if (this.labels[key] === undefined) {
            const choice = new GlideRecord('sys_choice');
            choice.addQuery('name', table);
            choice.addQuery('element', element);
            choice.addQuery('value', value);
            choice.addQuery('language', 'en');
            choice.setLimit(1);
            choice.query();
            this.labels[key] = choice.next() ? choice.getValue('label') : value;
        }
        return this.labels[key];
    },

    type: 'AssetCiDrift'
};
