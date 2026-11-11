/**
 * UI action «Drift beheben» (fix drift) on <scope>_drift_finding, form button, client + server.
 * Client: the leading side must be chosen; the preview of exactly that side is confirmed.
 * Server: AssetCiDrift.fix() changes the other side and writes the toolkit audit log.
 */
function itamkitFixDrift() {
    const side = g_form.getValue('leading_side');
    if (!side) {
        g_form.showFieldMsg('leading_side', 'Choose which side leads: asset or CI', 'error');
        return false;
    }
    const preview = g_form.getValue(side === 'asset' ? 'preview_asset_leads' : 'preview_ci_leads');
    if (!confirm('Fix drift (' + (side === 'asset' ? 'asset leads' : 'CI leads') + ')?\n\n' + preview +
        '\n\nThe change is written to the ITAM Toolkit audit log.')) {
        return false;
    }
    gsftSubmit(null, g_form.getFormElement(), 'itamkit_fix_drift');
}

if (typeof window == 'undefined') {
    itamkitFixDriftServer();
}

function itamkitFixDriftServer() {
    // Do not call current.update(): fix() already saved the finding.
    const result = new AssetCiDrift().fix(current.getUniqueValue(), current.getValue('leading_side'));
    if (result.success) {
        gs.addInfoMessage(result.message);
    } else {
        gs.addErrorMessage(result.message);
    }
    action.setRedirectURL(current);
}
