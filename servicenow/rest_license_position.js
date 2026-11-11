/**
 * Scripted REST API «ITAM Demo» (API-ID itam_demo), Ressource GET /license_position
 *
 * Liefert die gespeicherte Lizenzposition einer Firma aus u_itam_license_position,
 * nur lesend (nur GET, das Skript schreibt nichts). Für Prüfskripte und den
 * KI-Assistenten, die die Tabelle selbst nicht lesen sollen.
 * Parameter: company (Standard «Muster AG»).
 */
(function process(/*RESTAPIRequest*/ request, /*RESTAPIResponse*/ response) {
    var param = request.queryParams.company;
    var companyName = param && param.length ? String(param[0]) : 'Muster AG';
    var positions = [];
    var calculatedAt = '';
    var pos = new GlideRecord('u_itam_license_position');
    pos.addQuery('u_company.name', companyName);
    pos.orderBy('u_difference');
    pos.query();
    while (pos.next()) {
        positions.push({
            product: pos.u_software_model.name.toString(),
            publisher: pos.getValue('u_publisher'),
            metric: pos.getValue('u_metric'),
            rights: parseInt(pos.getValue('u_rights'), 10),
            usage: parseInt(pos.getValue('u_usage'), 10),
            difference: parseInt(pos.getValue('u_difference'), 10),
            status: pos.getValue('u_status')
        });
        if (pos.getValue('sys_updated_on') > calculatedAt) calculatedAt = pos.getValue('sys_updated_on');
    }
    // JSON.stringify statt Rückgabe des Objekts: sonst kommen ganze Zahlen als 5.0 an
    response.setContentType('application/json');
    response.setStatus(200);
    response.getStreamWriter().writeString(JSON.stringify({
        result: {company: companyName, calculated_at: calculatedAt, positions: positions}
    }));
})(request, response);
