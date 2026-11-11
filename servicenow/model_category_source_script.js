/**
 * Source Script der Feldzuordnung u_category -> cmdb_model_category
 * (Transform Map «Muster AG Modelle»). Das Zielfeld ist eine Liste, darum
 * wird der Name der Modellkategorie hier in ihre sys_id übersetzt.
 * Die Modellkategorie steuert, ob ServiceNow zu einem CI automatisch ein
 * Asset anlegt (Firewalls: keine Kategorie mit Asset-Klasse).
 */
answer = (function transformEntry(source) {
    var BY_CATEGORY = {
        laptop: 'Computer', desktop: 'Computer', server: 'Server',
        printer: 'Printer', smartphone: 'Hardware'
    };
    var category = String(source.getValue('u_category'));
    var name = category == 'network'
        ? (String(source.getValue('u_manufacturer')) == 'Fortinet' ? 'Network Gear' : 'IP Switch')
        : BY_CATEGORY[category];
    var gr = new GlideRecord('cmdb_model_category');
    return gr.get('name', name) ? gr.getUniqueValue() : '';
})(source);
