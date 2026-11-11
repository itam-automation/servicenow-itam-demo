/**
 * Script Include «MusterSamImport» (global, nur serverseitig)
 * Nachschlagefunktionen für die Transform Maps des SAM-Imports
 * (Software, Installationen, Lizenzen). Die Feldzuordnungen rufen nur diese
 * Funktionen auf, damit die Logik an einer Stelle steht.
 */
var MusterSamImport = Class.create();
MusterSamImport.COMPANY = 'Muster AG';
// Lizenzmetrik der Testdaten -> Lizenztyp der Plattform (cmdb_sw_license_calculation)
MusterSamImport.LICENSE_TYPES = {'Per User': 'Per named user', 'Per Device': 'Per workstation'};

MusterSamImport.prototype = {
    initialize: function () {},

    /** Hersteller per Name; fehlt er, wird er als Hersteller angelegt. */
    manufacturer: function (name) {
        if (!name) return '';
        var company = new GlideRecord('core_company');
        if (company.get('name', name)) return company.getUniqueValue();
        company.initialize();
        company.setValue('name', name);
        company.setValue('manufacturer', true);
        return company.insert();
    },

    /** Lizenztyp der Plattform zur Metrik; «Free» und Unbekanntes bleiben leer. */
    licenseType: function (metric) {
        var name = MusterSamImport.LICENSE_TYPES[metric];
        if (!name) return '';
        var type = new GlideRecord('cmdb_sw_license_calculation');
        return type.get('name', name) ? type.getUniqueValue() : '';
    },

    /** Normalisiertes Softwaremodell, auf das sich Lizenzen beziehen. */
    softwareModel: function (product, publisher) {
        var model = new GlideRecord('cmdb_software_product_model');
        model.addQuery('name', product);
        model.addQuery('manufacturer.name', publisher);
        model.query();
        return model.next() ? model.getUniqueValue() : '';
    },

    /** Softwarepaket, wie ein Inventar-Tool es meldet: Rohname und Version. */
    softwarePackage: function (displayName, version) {
        var pkg = new GlideRecord('cmdb_ci_spkg');
        pkg.addQuery('name', displayName);
        pkg.addQuery('version', version);
        pkg.query();
        return pkg.next() ? pkg.getUniqueValue() : '';
    },

    /** Gerät der Muster AG per Name (Inventarname; die IRE hat Scan-Dubletten zusammengeführt). */
    device: function (name) {
        var ci = new GlideRecord('cmdb_ci_hardware');
        ci.addQuery('name', name);
        ci.addQuery('company.name', MusterSamImport.COMPANY);
        ci.orderBy('sys_created_on');
        ci.query();
        return ci.next() ? ci.getUniqueValue() : '';
    },

    company: function () {
        var company = new GlideRecord('core_company');
        return company.get('name', MusterSamImport.COMPANY) ? company.getUniqueValue() : '';
    },

    /** Je Version ein Softwarepaket anlegen bzw. aktualisieren und mit dem Modell verknüpfen. */
    upsertPackages: function (modelId, manufacturerId, displayName, versions) {
        var count = 0;
        var list = (versions || '').split('|');
        for (var i = 0; i < list.length; i++) {
            var version = list[i].trim();
            if (!version) continue;
            var pkg = new GlideRecord('cmdb_ci_spkg');
            pkg.addQuery('name', displayName);
            pkg.addQuery('version', version);
            pkg.query();
            if (!pkg.next()) {
                pkg.initialize();
                pkg.setValue('name', displayName);
                pkg.setValue('version', version);
            }
            pkg.setValue('manufacturer', manufacturerId);
            pkg.setValue('model_id', modelId);
            if (pkg.isNewRecord()) pkg.insert(); else pkg.update();
            count++;
        }
        return count;
    },

    type: 'MusterSamImport'
};
