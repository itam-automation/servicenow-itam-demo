/**
 * onComplete-Skript der Transform Map «Muster AG Lizenzen»
 * (Quelle u_muster_license_imp, Ziel alm_license).
 *
 * Nach dem Lizenzimport die Lizenzposition neu berechnen (Script Include
 * «ItamLicensePosition»). Der Scheduled Job «ITAM: Lizenzposition berechnen»
 * macht dasselbe täglich, damit neue Installationen ohne Import auffallen.
 */
(function runTransformScript(source, map, log, target /*undefined onStart*/) {
    var rows = new ItamLicensePosition(MusterSamImport.COMPANY).store();
    log.info('Lizenzposition neu berechnet: ' + rows + ' Produkte');
})(source, map, log, target);
