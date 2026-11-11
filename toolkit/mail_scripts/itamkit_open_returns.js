/**
 * Mail script «itamkit_open_returns»: open return tasks of a leaver case,
 * used by the reminder and escalation notifications.
 */
(function runMailScript(/* GlideRecord */ current, /* TemplatePrinter */ template,
    /* Optional EmailOutbound */ email, /* Optional GlideRecord */ email_action, /* Optional GlideRecord */ event) {
    const task = new GlideRecord('asset_task');
    task.addQuery('parent', current.getUniqueValue());
    task.addActiveQuery();
    task.orderBy('number');
    task.query();
    template.print('<ul>');
    while (task.next()) {
        template.print('<li>' + task.asset.getDisplayValue() + ' (' + task.asset.model.getDisplayValue() + '), task ' +
            task.getValue('number') + '</li>');
    }
    template.print('</ul>');
})(current, template, email, email_action, event);
