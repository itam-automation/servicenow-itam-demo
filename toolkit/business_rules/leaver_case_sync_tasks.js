/**
 * Business rule «ITAM Toolkit: create return tasks» on <scope>_leaver_case, after insert.
 * Creates one asset_task per hardware asset still assigned to the leaver.
 * Idempotent: LeaverAssetResolver.resolve() calls syncTasks() again and gets 208.
 */
(function executeRule(current, previous /*null when async*/) {
    const result = new LeaverAssetResolver().syncTasks(current);
    if (!result.success) {
        gs.addErrorMessage(result.message);
    } else if (gs.getSession().isInteractive()) {
        gs.addInfoMessage(current.getValue('number') + ': ' + result.data.tasks_total + ' return task(s) for the leaver\'s hardware.');
    }
})(current, previous);
