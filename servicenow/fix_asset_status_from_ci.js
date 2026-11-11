/**
 * Fix Script «ITAM: Asset-Status an CI angleichen» (einmalig, als admin).
 *
 * Gleicht den Lifecycle-Status der Assets der Muster AG an ihr CI an. Nötig für
 * Assets, die vor der Business Rule «ITAM: Lifecycle-Status Hardware-Asset»
 * entstanden sind: ServiceNow hatte sie alle als «In use» angelegt.
 * setWorkflow(false): keine Business Rules, keine Rücksynchronisation aufs CI;
 * die CIs und damit die Messung der Datenqualität bleiben unverändert.
 */
var FROM_CI = {'1': '1', '3': '3', '6': '6', '7': '7'};
var gr = new GlideRecord('alm_hardware');
gr.addQuery('ci.company.name', 'Muster AG');
gr.query();
var changed = 0;
while (gr.next()) {
    var ciStatus = gr.ci.install_status.toString();
    var target = FROM_CI[ciStatus];
    if (target && target != gr.getValue('install_status')) {
        gr.setValue('install_status', target);
        gr.setValue('substatus', ciStatus == '6' ? 'available' : '');
        gr.setWorkflow(false);
        gr.update();
        changed++;
    }
}
gs.info('ITAM Fix: ' + changed + ' Assets an den CI-Status angeglichen');
