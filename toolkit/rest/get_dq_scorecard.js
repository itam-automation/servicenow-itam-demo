/** GET /dq/scorecard?name=<scorecard>: latest snapshot with rule results and rule definitions; role user. */
(function process(/*RESTAPIRequest*/ request, /*RESTAPIResponse*/ response) {
    ItamKitRest.handle(request, response, 'user', function () {
        return new DqScorecard().latest(ItamKitRest.param(request, 'name', ''));
    });
})(request, response);
