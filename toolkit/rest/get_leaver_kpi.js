/** GET /leaver/kpi?company=<sys_id>: return rate and cycle time of closed leaver cases; role user. */
(function process(/*RESTAPIRequest*/ request, /*RESTAPIResponse*/ response) {
    ItamKitRest.handle(request, response, 'user', function () {
        const company = ItamKitRest.param(request, 'company', '');
        return new LeaverAssetResolver().kpis(company ? 'company=' + company : '');
    });
})(request, response);
