/** GET /health: app version and scope; role user. */
(function process(/*RESTAPIRequest*/ request, /*RESTAPIResponse*/ response) {
    ItamKitRest.handle(request, response, 'user', function () {
        const app = new GlideRecord('sys_scope');
        app.get('scope', ItamKitConfig.scope());
        return ItamKitResult.ok(200, 'ITAM Toolkit ' + app.getValue('version') + ' is running', {
            app: app.getValue('name'), version: app.getValue('version'), scope_suffix: 'itamkit'
        });
    });
})(request, response);
