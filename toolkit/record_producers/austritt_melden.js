/**
 * Record producer «Austritt melden» (report a leaver) on <scope>_leaver_case.
 * Trigger (a) of module 1, primary path: HR reports the leaver with the last working day.
 * Variables: leaver, last_working_day, private_email (optional), note.
 * An open case for the same leaver is updated instead of creating a second one.
 */
(function (current, producer) {
    const result = new LeaverAssetResolver().prepareReportedCase(current, producer);
    if (result.status_code === 208) {
        gs.addInfoMessage(result.message);
        producer.redirect = ItamKitConfig.table('leaver_case') + '.do?sys_id=' + result.data.case_id;
    } else if (!result.success) {
        gs.addErrorMessage(result.message);
    } else if (producer.note) {
        current.work_notes = 'HR: ' + producer.note;
    }
})(current, producer);
