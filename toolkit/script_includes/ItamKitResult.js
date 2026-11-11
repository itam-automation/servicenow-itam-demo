/**
 * ItamKitResult: the output contract of every ITAM Toolkit building block.
 *
 * Every public method of the toolkit returns
 *     { success: boolean, status_code: number, message: string, data?: object }
 * The REST API passes the same object through, so callers (flows, scripts,
 * Python checks) never have to parse log lines.
 *
 * status_code follows HTTP semantics:
 *   200 done, 201 created, 204 nothing to do, 208 already done (idempotent repeat),
 *   400 invalid input, 403 missing role, 404 not found, 409 conflict with the current state,
 *   422 configuration invalid (for example a DQ rule with an unknown field), 500 unexpected error.
 */
var ItamKitResult = Class.create();

ItamKitResult.make = function (success, statusCode, message, data) {
    const result = {success: success, status_code: statusCode, message: String(message)};
    if (data !== undefined) result.data = data;
    return result;
};

ItamKitResult.ok = function (statusCode, message, data) {
    return ItamKitResult.make(true, statusCode, message, data);
};

ItamKitResult.fail = function (statusCode, message, data) {
    return ItamKitResult.make(false, statusCode, message, data);
};

ItamKitResult.fromError = function (err, context) {
    const text = (err && err.message) ? err.message : String(err);
    gs.error('ITAM Toolkit ' + context + ': ' + text);
    return ItamKitResult.fail(500, context + ' failed: ' + text);
};

ItamKitResult.prototype = {
    type: 'ItamKitResult'
};
