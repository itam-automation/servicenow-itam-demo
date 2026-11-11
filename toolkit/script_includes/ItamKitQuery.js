/**
 * ItamKitQuery: checks encoded queries before the toolkit relies on them.
 *
 * ServiceNow silently drops query terms with an unknown field: a typo in
 * "assigned_to.actve=false" turns a filter into "all records". Every configurable
 * query of the toolkit (DQ rules, the leaver asset filter) goes through
 * unknownFields() first and is rejected with status 422 instead.
 */
var ItamKitQuery = Class.create();

// Longest operators first, so "NOT IN" wins over "IN" and "!=" over "=".
ItamKitQuery.OPERATOR = /^([a-z0-9_.]+?)(ISNOTEMPTY|ISEMPTY|ANYTHING|EMPTYSTRING|NOT IN|NOT LIKE|NOTLIKE|NSAMEAS|SAMEAS|STARTSWITH|ENDSWITH|DATEPART|RELATIVEGT|RELATIVELT|RELATIVEGE|RELATIVELE|BETWEEN|NOTON|ON|LIKE|IN|!=|>=|<=|=|>|<)/;

/** Splits an encoded query into its terms (AND and OR terms alike). */
ItamKitQuery.terms = function (query) {
    if (!query) return [];
    return String(query).split(/\^OR|\^NQ|\^/).filter(function (t) {
        return t && t !== 'EQ' && t.indexOf('ORDERBY') !== 0;
    });
};

/** True if the field path (dot-walk allowed) exists, starting at the given table. */
ItamKitQuery.isValidPath = function (table, path) {
    let gr = new GlideRecord(table);
    if (!gr.isValid()) return false;
    const parts = path.split('.');
    for (let i = 0; i < parts.length; i++) {
        if (!gr.isValidField(parts[i])) return false;
        if (i === parts.length - 1) return true;
        const element = gr.getElement(parts[i]);
        const refTable = element.getReferenceTable ? element.getReferenceTable() : '';
        if (!refTable) return false;
        gr = new GlideRecord(refTable);
        if (!gr.isValid()) return false;
    }
    return true;
};

/**
 * Returns the problems of an encoded query on a table (empty array = valid):
 * unknown fields, terms without a recognised operator, and ^NQ (not supported,
 * because the toolkit combines queries with ^).
 */
ItamKitQuery.problems = function (table, query) {
    const problems = [];
    if (!query) return problems;
    if (String(query).indexOf('^NQ') >= 0) problems.push('^NQ is not supported');
    ItamKitQuery.terms(query).forEach(function (term) {
        const match = term.match(ItamKitQuery.OPERATOR);
        if (!match) {
            problems.push('no operator in "' + term + '"');
        } else if (!ItamKitQuery.isValidPath(table, match[1])) {
            problems.push('unknown field "' + match[1] + '" on ' + table);
        }
    });
    return problems;
};

/** Joins encoded queries with AND, skipping empty parts. */
ItamKitQuery.and = function () {
    return Array.prototype.slice.call(arguments).filter(function (q) {
        return q;
    }).join('^');
};

ItamKitQuery.prototype = {
    type: 'ItamKitQuery'
};
