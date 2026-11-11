/**
 * onBefore-Skript der Transform Map «Muster AG Installationen»
 * (Quelle u_muster_installation_imp, Ziel cmdb_software_instance).
 *
 * Die Feldzuordnungen lösen Softwarepaket und Gerät auf und koaleszieren auf
 * beiden (eine Installation je Paket und Gerät, wiederholte Läufe erzeugen
 * keine Dubletten). Fehlt eines davon, wird die Zeile als Fehler markiert statt
 * eine Installation ohne Gerät oder ohne Software anzulegen.
 */
(function runTransformScript(source, map, log, target /*undefined onStart*/) {
    var sam = new MusterSamImport();
    var missing = [];
    if (!sam.softwarePackage(source.getValue('u_display_name'), source.getValue('u_version'))) {
        missing.push('Softwarepaket ' + source.getValue('u_display_name') + ' ' + source.getValue('u_version'));
    }
    if (!sam.device(source.getValue('u_installed_on'))) {
        missing.push('Gerät ' + source.getValue('u_installed_on'));
    }
    if (missing.length) {
        error = true;
        error_message = 'Nicht gefunden: ' + missing.join(', ');
    }
})(source, map, log, target);
