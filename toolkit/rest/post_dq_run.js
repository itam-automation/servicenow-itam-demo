/** POST /dq/run?name=<scorecard>: drift scan for the scorecard's company, then a new snapshot; role admin. */
(function process(/*RESTAPIRequest*/ request, /*RESTAPIResponse*/ response) {
    ItamKitRest.handle(request, response, 'admin', function () {
        const dq = new DqScorecard();
        const card = dq._scorecard(ItamKitRest.param(request, 'name', ''));
        if (!card) return ItamKitResult.fail(404, 'Scorecard not found');
        const drift = new AssetCiDrift().scan(card.getValue('company'));
        const run = dq.run(card.getUniqueValue(), 'api');
        run.data = Object.assign({drift: drift}, run.data);
        return run;
    });
})(request, response);
