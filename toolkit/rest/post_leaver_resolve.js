/**
 * POST /leaver/resolve  body {user: sys_id or user_name, last_working_day: 'yyyy-MM-dd'}:
 * opens the leaver case for an HR system integration; role admin.
 */
(function process(/*RESTAPIRequest*/ request, /*RESTAPIResponse*/ response) {
    ItamKitRest.handle(request, response, 'admin', function () {
        const body = request.body.data || {};
        const user = new GlideRecord('sys_user');
        if (!body.user || !(user.get(body.user) || user.get('user_name', body.user))) {
            return ItamKitResult.fail(400, 'Body needs "user" (sys_id or user_name) of an existing user');
        }
        if (body.last_working_day && !/^\d{4}-\d{2}-\d{2}$/.test(body.last_working_day)) {
            return ItamKitResult.fail(400, 'last_working_day must be yyyy-MM-dd');
        }
        return new LeaverAssetResolver().resolve(user.getUniqueValue(), 'manual', {lastWorkingDay: body.last_working_day});
    });
})(request, response);
