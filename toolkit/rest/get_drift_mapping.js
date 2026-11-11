/** GET /drift/mapping: the OOTB asset/CI status mapping the drift watcher uses as target state; role user. */
(function process(/*RESTAPIRequest*/ request, /*RESTAPIResponse*/ response) {
    ItamKitRest.handle(request, response, 'user', function () {
        const drift = new AssetCiDrift();
        return ItamKitResult.ok(200, Object.keys(drift.toCi).length + ' mapping entries', {to_ci: drift.toCi, to_asset: drift.toAsset});
    });
})(request, response);
