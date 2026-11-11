/**
 * Shared helpers of the two request ATF tests (copied into both test scripts by build_bundle_requests.py,
 * because an ATF step script cannot import another script).
 *
 * newRequest() inserts a requested item with its variables directly. The platform starts a catalog flow
 * from the business rule «Start FlowDesigner Flow» only on an update, so the test runs the item's flow
 * itself in the foreground (sn_fd.FlowAPI) up to the approval, checks who has to approve, and cancels the
 * waiting flow before it changes anything else. The steps after the approval are the same script the flow
 * calls (ItamKitRequests); ATF rolls everything back after the run.
 */
const stamp = String(new GlideDateTime().getNumericValue());
const requests = new ItamKitRequests();

function insert(table, values) {
    const gr = new GlideRecord(table);
    gr.initialize();
    Object.keys(values).forEach(function (k) {
        gr.setValue(k, values[k]);
    });
    return gr.insert();
}

function load(table, id) {
    const gr = new GlideRecord(table);
    gr.get(id);
    return gr;
}

function newUser(name, managerId) {
    return insert('sys_user', Object.assign({user_name: 'atf.itamkit.req.' + name + '.' + stamp, first_name: 'ATF', last_name: name,
        email: 'atf.req.' + name + '@example.com'}, managerId ? {manager: managerId} : {}));
}

/** Computer CI and its hardware asset in use; returns {ci, asset}. */
function newDevice(name, values) {
    const ci = insert('cmdb_ci_computer', {name: 'ATF-REQ-' + name + '-' + stamp, install_status: '1'});
    const asset = new GlideRecord('alm_hardware');
    if (!asset.get('ci', ci)) {
        asset.initialize();
        asset.setValue('ci', ci);
    }
    asset.setValue('asset_tag', 'ATF-REQ-' + name + '-' + stamp);
    asset.setValue('install_status', '1');
    Object.keys(values || {}).forEach(function (k) {
        asset.setValue(k, values[k]);
    });
    const assetId = asset.isNewRecord() ? asset.insert() : (asset.update(), asset.getUniqueValue());
    return {ci: ci, asset: assetId};
}

function catalogItem(name) {
    const item = new GlideRecord('sc_cat_item');
    item.get('name', name);
    return item;
}

/** Requested item with variables, without starting the item's flow. */
function newRequest(item, requestedFor, variables) {
    const ritm = insert('sc_req_item', {cat_item: item.getUniqueValue(), requested_for: requestedFor,
        short_description: item.getValue('name') + ' (ATF)'});
    Object.keys(variables).forEach(function (name) {
        const question = new GlideRecord('item_option_new');
        question.addQuery('cat_item', item.getUniqueValue());
        question.addQuery('name', name);
        question.query();
        question.next();
        const option = insert('sc_item_option', {item_option_new: question.getUniqueValue(), value: variables[name]});
        insert('sc_item_option_mtom', {request_item: ritm, sc_item_option: option});
    });
    return load('sc_req_item', ritm);
}

/**
 * Runs the item's flow in the foreground until it waits for the approval; returns the context id.
 * The foreground runner stops at the approval and reports that as an exception ("waiting state");
 * the approval records exist at that point, so the waiting context is looked up instead.
 */
function runFlowToApproval(item, ritm) {
    const flow = item.flow_designer_flow.getRefRecord();
    const name = flow.sys_scope.scope.toString() + '.' + flow.getValue('internal_name');
    try {
        const result = sn_fd.FlowAPI.getRunner().flow(name).inForeground()
            .withInputs({request_item: ritm, table_name: 'sc_req_item'}).run();
        return result.getContextId();
    } catch (e) {
        if (String(e).indexOf('waiting state') < 0) throw e;
        const context = new GlideRecord('sys_flow_context');
        context.addQuery('flow', flow.getUniqueValue());
        context.addQuery('state', 'WAITING');
        context.orderByDesc('sys_created_on');
        context.setLimit(1);
        context.query();
        return context.next() ? context.getUniqueValue() : '';
    }
}

function cancelFlow(contextId) {
    if (contextId) sn_fd.FlowAPI.cancel(contextId, 'ATF: stopped after the approval check');
}

/** sys_ids of the users asked to approve the requested item. */
function approvers(ritm) {
    const ids = [];
    const approval = new GlideRecord('sysapproval_approver');
    approval.addQuery('sysapproval', ritm.getUniqueValue());
    approval.query();
    while (approval.next()) ids.push(approval.getValue('approver'));
    return ids;
}

function groupMembers(groupName) {
    const ids = [];
    const member = new GlideRecord('sys_user_grmember');
    member.addQuery('group.name', groupName);
    member.query();
    while (member.next()) ids.push(member.getValue('user'));
    return ids;
}

/** A rejected approval with a comment, as the approver would leave it. */
function rejectWith(ritm, approverId, comment) {
    const approval = new GlideRecord('sysapproval_approver');
    approval.initialize();
    approval.setValue('sysapproval', ritm.getUniqueValue());
    approval.setValue('source_table', 'sc_req_item');
    approval.setValue('document_id', ritm.getUniqueValue());
    approval.setValue('approver', approverId);
    approval.setValue('state', 'rejected');
    approval.comments = comment;
    return approval.insert();
}

function auditRows(recordId) {
    const audit = new GlideRecord(ItamKitConfig.table('audit_log'));
    audit.addQuery('target_id', recordId);
    audit.addQuery('module', 'request');
    audit.query();
    return audit.getRowCount();
}
