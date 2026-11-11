/**
 * Flow Designer action «ITAM Toolkit: run request step», script step (scope of the ITAM Toolkit app).
 * Source copy for review; the action itself is part of the update set «ITAM Toolkit 0.2.0».
 *
 * Inputs:  step (String: approver, start_return, complete_return, apply_change, reject)
 *          request (String; the flows pass the trigger's requested item record pill)
 * Outputs: success (True/False), status_code (Integer), message (String),
 *          approver_user (Reference sys_user), approver_group (Reference sys_user_group),
 *          return_task (String, sys_id of the asset_task)
 *
 * A record pill arrives in the script as a GlideRecord, not as a sys_id; String() would give
 * "[object GlideRecord]". The approver outputs are typed references because «Ask For Approval»
 * only resolves a group from a pill of type sys_user_group.
 */
(function execute(inputs, outputs) {
    var request = inputs.request; var result = new ItamKitRequests().run(String(inputs.step), request && request.getUniqueValue ? request.getUniqueValue() : String(request));
    var data = result.data || {};
    outputs.success = result.success;
    outputs.status_code = result.status_code;
    outputs.message = result.message;
    outputs.approver_user = data.approver_user || '';
    outputs.approver_group = data.approver_group || '';
    outputs.return_task = data.return_task || '';
})(inputs, outputs);
