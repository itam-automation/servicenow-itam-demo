/**
 * Script Include «ItamLicensePosition» (global, nur serverseitig)
 *
 * Lizenzposition je Softwaremodell einer Firma: gekaufte Rechte (alm_license)
 * gegen Nutzung (cmdb_software_instance auf Geräten der Firma). Ersetzt die
 * Compliance-Berechnung von SAM Pro, das auf der Entwicklerinstanz nicht aktiv
 * ist. Zählweise bewusst einfach und gleich wie im Testdaten-Generator:
 * - «Per workstation»: Geräte mit mindestens einer Installation des Produkts
 * - «Per named user»: verschiedene Benutzer dieser Geräte; Geräte ohne
 *   Benutzer zählen je einmal (sonst fiele ungenutzte Hardware durch)
 * Produkte ohne Lizenztyp (Freeware) zählen nur, wenn eine Lizenz existiert.
 *
 * Ergebnis in u_itam_license_position, eine Zeile je Produkt. Aufruf:
 *   new ItamLicensePosition('Muster AG').store()
 * (onComplete der Transform Map «Muster AG Lizenzen» und täglicher Scheduled Job).
 */
var ItamLicensePosition = Class.create();
ItamLicensePosition.TABLE = 'u_itam_license_position';
ItamLicensePosition.PER_USER = 'Per named user';
ItamLicensePosition.PER_DEVICE = 'Per workstation';

/** Gleiche Reihenfolge wie sam_expectation im Generator. */
ItamLicensePosition.status = function (licensed, rights, usage) {
    if (!licensed) return 'ohne Lizenz';
    if (usage == 0) return 'ungenutzt';
    if (rights < usage) return 'unterlizenziert';
    if (rights > usage) return 'überlizenziert';
    return 'ausgeglichen';
};

ItamLicensePosition.prototype = {
    initialize: function (companyName) {
        this.companyName = companyName || 'Muster AG';
    },

    /** Berechnet die Position; gibt eine Liste von Objekten zurück (schreibt nichts). */
    calculate: function () {
        var usage = {};   // Modell -> {Gerät: Benutzer}
        var rights = {};  // Modell -> Summe der Rechte

        var inst = new GlideRecord('cmdb_software_instance');
        inst.addQuery('installed_on.company.name', this.companyName);
        inst.addNotNullQuery('software.model_id');
        inst.query();
        while (inst.next()) {
            var modelId = inst.software.model_id.toString();
            usage[modelId] = usage[modelId] || {};
            usage[modelId][inst.getValue('installed_on')] = inst.installed_on.assigned_to.toString();
        }

        var lic = new GlideRecord('alm_license');
        lic.addQuery('company.name', this.companyName);
        lic.addQuery('install_status', '!=', '7');  // ausgemusterte Lizenzen zählen nicht
        lic.addNotNullQuery('model');
        lic.query();
        while (lic.next()) {
            var licModel = lic.getValue('model');
            rights[licModel] = (rights[licModel] || 0) + parseInt(lic.getValue('rights') || '0', 10);
        }

        var ids = {};
        var id;
        for (id in usage) ids[id] = true;
        for (id in rights) ids[id] = true;

        var rows = [];
        for (id in ids) {
            var model = new GlideRecord('cmdb_software_product_model');
            if (!model.get(id)) continue;
            var metric = model.license_type.getDisplayValue();
            var licensed = rights.hasOwnProperty(id);
            if (!licensed && metric != ItamLicensePosition.PER_USER && metric != ItamLicensePosition.PER_DEVICE) {
                continue;  // Freeware ohne Lizenz
            }
            var used = this._usage(usage[id] || {}, metric);
            var owned = rights[id] || 0;
            rows.push({
                model: id,
                product: model.getValue('name'),
                publisher: model.manufacturer.getDisplayValue(),
                metric: metric,
                rights: owned,
                usage: used,
                difference: owned - used,
                status: ItamLicensePosition.status(licensed, owned, used)
            });
        }
        rows.sort(function (a, b) { return a.difference - b.difference || (a.product < b.product ? -1 : 1); });
        return rows;
    },

    /** Berechnet und ersetzt die Zeilen der Firma in u_itam_license_position. */
    store: function () {
        var company = new GlideRecord('core_company');
        if (!company.get('name', this.companyName)) return 0;
        var rows = this.calculate();

        var old = new GlideRecord(ItamLicensePosition.TABLE);
        old.addQuery('u_company', company.getUniqueValue());
        old.deleteMultiple();

        for (var i = 0; i < rows.length; i++) {
            var r = rows[i];
            var pos = new GlideRecord(ItamLicensePosition.TABLE);
            pos.initialize();
            pos.setValue('u_company', company.getUniqueValue());
            pos.setValue('u_software_model', r.model);
            pos.setValue('u_publisher', r.publisher);
            pos.setValue('u_metric', r.metric);
            // String(): sonst speichert Rhino Zahlen als «20.0»
            pos.setValue('u_rights', String(r.rights));
            pos.setValue('u_usage', String(r.usage));
            pos.setValue('u_difference', String(r.difference));
            pos.setValue('u_status', r.status);
            pos.insert();
        }
        return rows.length;
    },

    _usage: function (devices, metric) {
        var count = 0;
        var users = {};
        for (var device in devices) {
            var user = devices[device];
            if (metric == ItamLicensePosition.PER_USER && user) {
                users[user] = true;
            } else {
                count++;  // pro Gerät, oder Gerät ohne Benutzer
            }
        }
        for (var u in users) count++;
        return count;
    },

    type: 'ItamLicensePosition'
};
