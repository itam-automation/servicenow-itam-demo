/**
 * Business rule «ITAM Toolkit: leaver on deactivation» on sys_user, after update,
 * condition: current.active.changesTo(false).
 * Trigger (b) of module 1. Mass deactivations that bypass business rules (imports, LDAP,
 * setWorkflow(false)) are caught by the nightly sweep instead.
 */
(function executeRule(current, previous /*null when async*/) {
    const result = new LeaverAssetResolver().resolve(current.getUniqueValue(), 'user_deactivated');
    if (!result.success) {
        gs.error('ITAM Toolkit leaver on deactivation: ' + result.message);
    } else if (result.status_code === 201 && gs.getSession().isInteractive()) {
        gs.addInfoMessage(result.message);
    }
})(current, previous);
