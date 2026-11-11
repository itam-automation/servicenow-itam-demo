/**
 * onAfter-Skript der Transform Map «Muster AG Software -> Softwaremodelle»
 * (Quelle u_muster_software_imp, Ziel cmdb_software_product_model).
 *
 * Normalisierung: Ein Inventar-Tool meldet Rohnamen mit Version
 * («Microsoft Visio - de-de» 16.0.18129.20116). Lizenzen beziehen sich auf das
 * Produkt («Visio Plan 2»). Je gemeldeter Version entsteht ein Softwarepaket
 * (cmdb_ci_spkg), das über model_id auf das Softwaremodell zeigt. Das ist von
 * Hand, was SAM Pro mit seiner Normalisierung automatisch erledigt.
 */
(function runTransformScript(source, map, log, target /*undefined onStart*/) {
    var count = new MusterSamImport().upsertPackages(
        target.getUniqueValue(),
        target.getValue('manufacturer'),
        source.getValue('u_display_name'),
        source.getValue('u_versions')
    );
    log.info('Softwaremodell ' + target.getValue('name') + ': ' + count + ' Softwarepakete');
})(source, map, log, target);
