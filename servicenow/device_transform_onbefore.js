/**
 * onBefore-Transformskript der Transform Map «Muster AG Geräte -> CMDB (IRE)».
 * Quelle: Staging-Tabelle u_muster_device_imp, Ziel: cmdb_ci_hardware.
 *
 * Die Transform Map schreibt selbst nichts. Jede Zeile geht über die
 * Identification and Reconciliation Engine (IRE), damit Dubletten aus
 * mehreren Quellen erkannt und zusammengeführt werden:
 * - Referenzen (Firma, Hersteller, Modell, Benutzer, Standort, Abteilung)
 *   werden hier aufgelöst. Fehlende Hersteller werden so angelegt, wie die
 *   Quelle sie liefert (Schreibvarianten bleiben sichtbar für den Report).
 * - Seriennummern werden normalisiert (Leerzeichen weg, Grossbuchstaben).
 *   Ohne diesen Schritt hat die IRE Schreibvarianten nicht als Dublette
 *   erkannt (erster Lauf: 9 von 12 Scan-Dubletten zusammengeführt).
 * - Das Ergebnis der IRE steht in den Spalten u_ire_* der Staging-Zeile und
 *   im Kommentar der Zeile; daraus liest der Loader den Lauf zurück.
 */
(function runTransformScript(source, map, log, target) {
    var DATA_SOURCES = {'Inventar-Export': 'MusterInventar', 'Netzwerk-Scan': 'MusterNetzScan'};
    var STATUS = {
        'Installed': '1', 'On Order': '2', 'In Maintenance': '3', 'Pending Install': '4',
        'Pending Repair': '5', 'In Stock': '6', 'Retired': '7', 'Stolen': '8', 'Absent': '100'
    };
    var COMPUTER_CLASSES = ['cmdb_ci_computer', 'cmdb_ci_win_server', 'cmdb_ci_linux_server'];
    var COMPUTER_FIELDS = ['os', 'os_version', 'cpu_core_count', 'ram', 'disk_space'];
    var PLAIN_FIELDS = ['name', 'asset_tag', 'ip_address', 'mac_address', 'purchase_date', 'warranty_expiration', 'cost'];

    function val(field) {
        var v = source.getValue('u_' + field);
        return v ? String(v).trim() : '';
    }

    function find(table, field, value, extraField, extraValue) {
        var gr = new GlideRecord(table);
        gr.addQuery(field, value);
        if (extraField) {
            gr.addQuery(extraField, extraValue);
        }
        gr.setLimit(1);
        gr.query();
        return gr.next() ? gr.getUniqueValue() : '';
    }

    function manufacturer(name) {
        var id = find('core_company', 'name', name);
        if (id) {
            return id;
        }
        var gr = new GlideRecord('core_company');
        gr.initialize();
        gr.setValue('name', name);
        gr.setValue('manufacturer', true);
        return gr.insert();
    }

    var className = val('sn_class');
    var dataSource = DATA_SOURCES[val('source')];
    if (!className || !dataSource) {
        error = true;
        error_message = 'Klasse oder Quelle fehlt/unbekannt: ' + className + ' / ' + val('source');
        return;
    }

    var values = {};
    PLAIN_FIELDS.forEach(function (f) {
        if (val(f)) {
            values[f] = val(f);
        }
    });
    if (val('serial_number')) {
        values.serial_number = val('serial_number').replace(/\s+/g, '').toUpperCase();
    }
    if (COMPUTER_CLASSES.indexOf(className) >= 0) {
        COMPUTER_FIELDS.forEach(function (f) {
            if (val(f)) {
                values[f] = val(f);
            }
        });
    }
    if (val('install_status')) {
        values.install_status = STATUS[val('install_status')];
    }

    var companyId = val('company') ? find('core_company', 'name', val('company')) : '';
    var refs = {
        company: companyId,
        manufacturer: val('manufacturer') ? manufacturer(val('manufacturer')) : '',
        model_id: val('model_id') ? find('cmdb_hardware_product_model', 'name', val('model_id')) : '',
        assigned_to: val('assigned_to') ? find('sys_user', 'user_name', val('assigned_to')) : '',
        location: val('location') ? find('cmn_location', 'name', val('location')) : '',
        department: val('department') ? find('cmn_department', 'name', val('department'), 'company', companyId) : ''
    };
    var missing = [];
    for (var field in refs) {
        if (refs[field]) {
            values[field] = refs[field];
        } else if (val(field)) {
            missing.push(field + '=' + val(field));
        }
    }

    var payload = {
        items: [{
            className: className,
            values: values,
            sys_object_source_info: {source_name: dataSource, source_native_key: val('source_id')}
        }]
    };
    var output = JSON.parse(sn_cmdb.IdentificationEngine.createOrUpdateCI(dataSource, JSON.stringify(payload)));
    var item = output.items[0];
    var errors = (item.errors || []).map(function (e) {
        return e.message || e.error;
    });
    var matched = (item.identificationAttempts || []).filter(function (a) {
        return a.attemptResult == 'MATCHED';
    }).map(function (a) {
        return (a.attributes || []).join('+');
    });

    source.setValue('u_ire_operation', item.operation || '');
    source.setValue('u_ire_ci', item.sysId || '');
    source.setValue('u_ire_match', matched.join(', '));
    source.setValue('u_ire_missing', missing.join(', '));
    source.sys_import_state_comment = 'IRE ' + (item.operation || '') + ' ' + (item.sysId || '') +
        (matched.length ? ' via ' + matched.join(', ') : '') + (errors.length ? ' Fehler: ' + errors.join('; ') : '');

    if (errors.length) {
        error = true;
        error_message = 'IRE: ' + errors.join('; ');
    } else {
        // Die IRE hat das CI geschrieben; die Transform Map selbst schreibt nichts.
        ignore = true;
    }
})(source, map, log, target);
