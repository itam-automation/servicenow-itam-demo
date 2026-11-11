/**
 * Scheduled job «ITAM Toolkit: leaver sweep», daily.
 * Trigger (c) of module 1: leavers whose deactivation bypassed the business rule,
 * resync of all open cases, reminders on day 3, 7, 14 (escalation).
 */
(function () {
    const result = new LeaverAssetResolver().sweep();
    gs.info('ITAM Toolkit leaver sweep: ' + JSON.stringify(result));
})();
