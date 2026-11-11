/**
 * UI actions on asset_task (form buttons), one per outcome:
 * «Returned: in stock», «Returned: needs repair», «Returned: for disposal», «Missing / lost».
 * Condition: new LeaverAssetResolver().isLeaverTask(current) && current.active == true
 * The deploy script replaces __OUTCOME__ with in_stock, pending_repair, pending_disposal, missing_lost.
 */
LeaverAssetResolver.uiComplete(current, '__OUTCOME__');
action.setRedirectURL(current);
