/**
 * DqScorecard: weighted data quality score from a configurable rule table.
 *
 * Rule (<scope>_dq_rule): table, rule type, population query, defect query, dimension,
 * weight, group, remediation hint. Rule types:
 *   query          defects = population AND defect query
 *   duplicate      defects = surplus records sharing a non-empty value of duplicate_field
 *   field_mismatch defects = records where field and compare_field are both set and differ
 *   drift          defects = assets whose CI status differs from the OOTB asset/CI status mapping
 * Rule score = 100 * (1 - defects / population); rules with an empty population are skipped.
 * Scorecard score = sum(weight * rule score) / sum(weight).
 *
 * A scorecard (<scope>_dq_scorecard) can be limited to one company: the engine adds
 * "<company_field>=<company>" to every rule. Each run writes a snapshot
 * (<scope>_dq_snapshot) with one result row per rule (<scope>_dq_result); the trend is a
 * line report on the snapshots, without Performance Analytics.
 */
var DqScorecard = Class.create();

DqScorecard.prototype = {
    initialize: function () {
        this.ruleTable = ItamKitConfig.table('dq_rule');
        this.scorecardTable = ItamKitConfig.table('dq_scorecard');
        this.snapshotTable = ItamKitConfig.table('dq_snapshot');
        this.resultTable = ItamKitConfig.table('dq_result');
    },

    /** Runs all active rules for a scorecard (sys_id or name) and stores a snapshot. */
    run: function (scorecard, trigger) {
        try {
            const card = this._scorecard(scorecard);
            if (!card) return ItamKitResult.fail(404, 'Scorecard not found: ' + scorecard);
            const started = new GlideDateTime().getNumericValue();
            const companyId = card.getValue('company');

            const snapshot = new GlideRecord(this.snapshotTable);
            snapshot.initialize();
            snapshot.setValue('scorecard', card.getUniqueValue());
            snapshot.setValue('trigger', trigger || 'manual');
            snapshot.setValue('snapshot_label', card.getValue('name') + ' ' + new GlideDateTime().getDisplayValue());
            const snapshotId = snapshot.insert();

            let weighted = 0;
            let weights = 0;
            const counts = {evaluated: 0, invalid: 0, empty: 0, population: 0, defects: 0};
            const rows = [];
            const rule = new GlideRecord(this.ruleTable);
            rule.addActiveQuery();
            rule.orderBy('order');
            rule.orderBy('name');
            rule.query();
            while (rule.next()) {
                const r = this.evaluate(rule, companyId);
                const weight = parseInt(rule.getValue('weight') || '1', 10);
                const result = new GlideRecord(this.resultTable);
                result.initialize();
                result.setValue('snapshot', snapshotId);
                result.setValue('rule', rule.getUniqueValue());
                result.setValue('status', r.status);
                result.setValue('weight', weight);
                result.setValue('dimension', rule.getValue('dimension'));
                result.setValue('rule_group', rule.getValue('rule_group'));
                result.setValue('message', r.message);
                if (r.status === 'ok') {
                    result.setValue('population', r.population);
                    result.setValue('defects', r.defects);
                    result.setValue('score', this._round(r.score));
                    weighted += weight * r.score;
                    weights += weight;
                    counts.evaluated++;
                    counts.population += r.population;
                    counts.defects += r.defects;
                } else {
                    counts[r.status]++;
                }
                result.insert();
                rows.push({code: rule.getValue('code'), rule: rule.getValue('name'), status: r.status, population: r.population, defects: r.defects,
                    score: r.status === 'ok' ? this._round(r.score) : null, weight: weight, message: r.message});
            }

            const score = weights ? this._round(weighted / weights) : null;
            snapshot.get(snapshotId);
            snapshot.setValue('score', score === null ? '' : score);
            snapshot.setValue('rules_evaluated', counts.evaluated);
            snapshot.setValue('rules_invalid', counts.invalid);
            snapshot.setValue('rules_empty', counts.empty);
            snapshot.setValue('population_total', counts.population);
            snapshot.setValue('defects_total', counts.defects);
            snapshot.setValue('duration_ms', new GlideDateTime().getNumericValue() - started);
            snapshot.update();

            const message = card.getValue('name') + ': score ' + score + ' from ' + counts.evaluated + ' rule(s)' +
                (counts.invalid ? ', ' + counts.invalid + ' invalid rule(s) skipped' : '') +
                (counts.empty ? ', ' + counts.empty + ' rule(s) without population' : '');
            const data = {snapshot_id: snapshotId, snapshot: snapshot.getDisplayValue(), score: score, counts: counts, rules: rows};
            return counts.invalid ? ItamKitResult.fail(422, message, data) : ItamKitResult.ok(201, message, data);
        } catch (e) {
            return ItamKitResult.fromError(e, 'DqScorecard.run');
        }
    },

    /** Evaluates one rule: {status: ok|invalid|empty, population, defects, score, message}. */
    evaluate: function (rule, companyId) {
        const table = rule.getValue('table_name');
        const type = rule.getValue('rule_type') || 'query';
        const companyField = rule.getValue('company_field');
        const scope = companyId && companyField ? companyField + '=' + companyId : '';
        const population = ItamKitQuery.and(scope, rule.getValue('population_query'));
        const defectQuery = rule.getValue('defect_query');

        const problems = ItamKitQuery.problems(table, population)
            .concat(type === 'query' ? ItamKitQuery.problems(table, defectQuery) : []);
        if (type === 'query' && !defectQuery) problems.push('defect query is empty');
        if (type === 'duplicate' && !ItamKitQuery.isValidPath(table, rule.getValue('field') || '')) problems.push('duplicate field is not valid');
        if (type === 'field_mismatch') {
            if (!ItamKitQuery.isValidPath(table, rule.getValue('field') || '')) problems.push('field is not valid');
            if (!ItamKitQuery.isValidPath(table, rule.getValue('compare_field') || '')) problems.push('compare field is not valid');
        }
        if (type === 'drift' && table !== 'alm_hardware') problems.push('drift rules run on alm_hardware');
        if (problems.length) return {status: 'invalid', message: problems.join('; ')};

        let population_count;
        let defects;
        if (type === 'drift') {
            const drift = new AssetCiDrift().count(companyId).data;
            population_count = drift.population;
            defects = drift.defects;
        } else {
            population_count = this._count(table, population);
            if (type === 'query') defects = this._count(table, ItamKitQuery.and(population, defectQuery));
            if (type === 'duplicate') defects = this._duplicates(table, population, rule.getValue('field'));
            if (type === 'field_mismatch') defects = this._mismatches(table, population, rule.getValue('field'), rule.getValue('compare_field'));
        }
        if (!population_count) return {status: 'empty', population: 0, defects: 0, message: 'no records in the population'};
        return {status: 'ok', population: population_count, defects: defects,
            score: 100 * (1 - defects / population_count), message: defects + ' of ' + population_count};
    },

    /** Latest snapshot of a scorecard with its results and the rule definitions (for the REST API). */
    latest: function (scorecard) {
        const card = this._scorecard(scorecard);
        if (!card) return ItamKitResult.fail(404, 'Scorecard not found: ' + scorecard);
        const snapshot = new GlideRecord(this.snapshotTable);
        snapshot.addQuery('scorecard', card.getUniqueValue());
        snapshot.orderByDesc('sys_created_on');
        snapshot.setLimit(1);
        snapshot.query();
        if (!snapshot.next()) return ItamKitResult.fail(404, 'No snapshot yet for ' + card.getValue('name'));
        const results = [];
        const result = new GlideRecord(this.resultTable);
        result.addQuery('snapshot', snapshot.getUniqueValue());
        result.orderBy('rule.order');
        result.query();
        while (result.next()) {
            const rule = result.rule.getRefRecord();
            results.push({
                code: rule.getValue('code'), rule: rule.getValue('name'), table: rule.getValue('table_name'), rule_type: rule.getValue('rule_type'),
                population_query: rule.getValue('population_query') || '', defect_query: rule.getValue('defect_query') || '',
                field: rule.getValue('field') || '', compare_field: rule.getValue('compare_field') || '',
                company_field: rule.getValue('company_field') || '', dimension: rule.getValue('dimension'),
                rule_group: rule.getValue('rule_group'), remediation: rule.getValue('remediation') || '',
                status: result.getValue('status'), weight: parseInt(result.getValue('weight'), 10),
                population: result.getValue('population') === null ? null : parseInt(result.getValue('population'), 10),
                defects: result.getValue('defects') === null ? null : parseInt(result.getValue('defects'), 10),
                score: result.getValue('score') === null ? null : parseFloat(result.getValue('score'))
            });
        }
        return ItamKitResult.ok(200, card.getValue('name') + ': score ' + snapshot.getValue('score') + ' (' + snapshot.getValue('sys_created_on') + ' UTC)', {
            scorecard: card.getValue('name'), company: card.getValue('company') || '', company_name: card.company.getDisplayValue(),
            snapshot: snapshot.getDisplayValue(), created_on: snapshot.getValue('sys_created_on'),
            score: snapshot.getValue('score') === null ? null : parseFloat(snapshot.getValue('score')), results: results
        });
    },

    // ------------------------------------------------------------------ helpers

    _scorecard: function (scorecard) {
        const card = new GlideRecord(this.scorecardTable);
        if (scorecard && card.get(scorecard)) return card;
        card.initialize();
        card.addActiveQuery();
        if (scorecard) card.addQuery('name', scorecard);
        card.orderBy('name');
        card.setLimit(1);
        card.query();
        return card.next() ? card : null;
    },

    _count: function (table, query) {
        const agg = new GlideAggregate(table);
        if (query) agg.addEncodedQuery(query);
        agg.addAggregate('COUNT');
        agg.query();
        return agg.next() ? parseInt(agg.getAggregate('COUNT'), 10) : 0;
    },

    /** Surplus records: a value shared by n records counts n - 1 times. */
    _duplicates: function (table, query, field) {
        let surplus = 0;
        const agg = new GlideAggregate(table);
        if (query) agg.addEncodedQuery(query);
        agg.addNotNullQuery(field);
        agg.groupBy(field);
        agg.addAggregate('COUNT');
        agg.query();
        while (agg.next()) {
            const n = parseInt(agg.getAggregate('COUNT'), 10);
            if (n > 1) surplus += n - 1;
        }
        return surplus;
    },

    _mismatches: function (table, query, field, compareField) {
        let mismatches = 0;
        const gr = new GlideRecord(table);
        if (query) gr.addEncodedQuery(query);
        gr.addNotNullQuery(field);
        gr.addNotNullQuery(compareField);
        gr.query();
        while (gr.next()) {
            if (this._value(gr, field) !== this._value(gr, compareField)) mismatches++;
        }
        return mismatches;
    },

    /** Value of a field path, dot-walk allowed ('model_id.manufacturer'). */
    _value: function (gr, path) {
        let element = gr;
        path.split('.').forEach(function (part) {
            element = element[part];
        });
        return element === undefined || element === null ? '' : element.toString();
    },

    _round: function (value) {
        return Math.round(value * 100) / 100;
    },

    type: 'DqScorecard'
};
