/**
 * ItamKitRest: shared code of the Scripted REST API «ITAM Toolkit» (API ID toolkit).
 * Every resource answers with the ItamKitResult contract as JSON body; the HTTP status is
 * the status_code, except 204 and 208, which are sent as 200 so the body arrives.
 */
var ItamKitRest = Class.create();

/** Returns a 403 result if the caller lacks the toolkit role, else null. */
ItamKitRest.guard = function (roleSuffix) {
    const role = ItamKitConfig.role(roleSuffix);
    if (gs.hasRole(role)) return null;
    return ItamKitResult.fail(403, 'Role ' + role + ' required');
};

ItamKitRest.param = function (request, name, fallback) {
    const value = request.queryParams[name];
    return value && value.length ? String(value[0]) : fallback;
};

ItamKitRest.send = function (response, result) {
    const http = (result.status_code === 204 || result.status_code === 208) ? 200 : result.status_code;
    response.setContentType('application/json');
    response.setStatus(http);
    // JSON.stringify instead of returning the object: otherwise integers arrive as 5.0
    response.getStreamWriter().writeString(JSON.stringify(result));
};

/** Runs a handler with role check and error contract. */
ItamKitRest.handle = function (request, response, roleSuffix, handler) {
    let result = ItamKitRest.guard(roleSuffix);
    if (!result) {
        try {
            result = handler();
        } catch (e) {
            result = ItamKitResult.fromError(e, 'REST ' + request.uri);
        }
    }
    ItamKitRest.send(response, result);
};

ItamKitRest.prototype = {
    type: 'ItamKitRest'
};
