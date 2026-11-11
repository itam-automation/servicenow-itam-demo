/**
 * Scheduled job «ITAM Toolkit: drift scan and DQ snapshot», daily.
 * Per active scorecard: refresh the drift findings of its company, then store a snapshot.
 */
(function () {
    const card = new GlideRecord(ItamKitConfig.table('dq_scorecard'));
    card.addActiveQuery();
    card.query();
    while (card.next()) {
        const drift = new AssetCiDrift().scan(card.getValue('company'));
        const snapshot = new DqScorecard().run(card.getUniqueValue(), 'scheduled');
        gs.info('ITAM Toolkit nightly ' + card.getValue('name') + ': ' + JSON.stringify({drift: drift, snapshot: {
            success: snapshot.success, status_code: snapshot.status_code, message: snapshot.message}}));
    }
})();
