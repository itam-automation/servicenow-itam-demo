/**
 * Business Rule «ITAM: Lifecycle-Status Hardware-Asset»
 * Tabelle: alm_hardware · when: before · insert und update · Reihenfolge 100
 * Bedingung: current.operation() == 'insert' || current.install_status.changes()
 *
 * Ergänzt die Standardregeln der Plattform auf alm_asset, statt sie zu doppeln:
 * - «Clear Assigned To on update»: Lager, Bestellung, Transport -> Zuweisung wird gelöscht.
 *   Wer ein Gerät aus dem Lager zuweist, setzt darum Status «In use» und Person
 *   gemeinsam (so macht es der Flow «Laptop anfordern»).
 * - «Asset Retirement»: Ausmusterung -> Datum, Zuweisung und Lagerort werden gelöscht.
 *
 * Was fehlt und diese Regel ergänzt:
 * 1. Neues Asset aus einem CI (Job «Asset – Create asset delayed sync»):
 *    Lifecycle-Status vom CI übernehmen. Ohne diese Regel legt ServiceNow jedes
 *    Asset als «In use» an, auch für CIs, die «In Stock» oder «Retired» sind
 *    (Endlauf Meilenstein 1: 61 von 197 Assets mit falschem Status).
 * 2. Asset geht in Betrieb: Zeitpunkt der Zuweisung festhalten, Unterstatus leeren.
 */
(function executeRule(current, previous /*null when async*/) {
    var IN_USE = '1';
    var IN_MAINTENANCE = '3';
    var IN_STOCK = '6';
    var RETIRED = '7';
    // install_status cmdb_ci -> alm_asset; für diese vier Zustände sind die Werte gleich
    var FROM_CI = {'1': IN_USE, '3': IN_MAINTENANCE, '6': IN_STOCK, '7': RETIRED};

    if (current.operation() == 'insert') {
        if (!current.ci.nil()) {
            var ciStatus = current.ci.install_status.toString();
            if (FROM_CI[ciStatus] && FROM_CI[ciStatus] != current.getValue('install_status')) {
                current.setValue('install_status', FROM_CI[ciStatus]);
                current.setValue('substatus', ciStatus == IN_STOCK ? 'available' : '');
            }
        }
        return;
    }

    if (current.getValue('install_status') == IN_USE && !current.assigned_to.nil()) {
        current.setValue('substatus', '');
        if (current.assigned_to.changes() || current.assigned.nil()) {
            current.setValue('assigned', new GlideDateTime().getValue());
        }
    }
})(current, previous);
