/** UI action «Run snapshot now» on <scope>_dq_scorecard: drift scan for the company, then a snapshot. */
const drift = new AssetCiDrift().scan(current.getValue('company'));
const run = new DqScorecard().run(current.getUniqueValue(), 'manual');
gs.addInfoMessage('Drift: ' + drift.message);
if (run.success) {
    gs.addInfoMessage(run.message);
} else {
    gs.addErrorMessage(run.message);
}
action.setRedirectURL(current);
