/** UI action «Sync return tasks» on <scope>_leaver_case: creates tasks for hardware assigned after the case was opened. */
const result = new LeaverAssetResolver().syncTasks(current);
if (result.success) {
    gs.addInfoMessage(result.message + '; ' + result.data.tasks_open + ' open of ' + result.data.tasks_total);
} else {
    gs.addErrorMessage(result.message);
}
action.setRedirectURL(current);
