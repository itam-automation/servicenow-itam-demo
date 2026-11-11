/**
 * ATF-Test «ITAM: Lifecycle-Status Hardware-Asset», Schritt «Run Server Side Script» (Jasmine 3.1).
 * Prüft die Business Rule servicenow/business_rule_asset_lifecycle.js und das
 * Standardverhalten der Plattform, auf das der Flow «Laptop anfordern» baut.
 * ATF setzt alle Änderungen nach dem Testlauf zurück (Rollback).
 */
(function (outputs, steps, params, stepResult, assertEqual) {
    var IN_USE = '1';
    var IN_STOCK = '6';
    var RETIRED = '7';

    function newComputerCi(name, status) {
        var ci = new GlideRecord('cmdb_ci_computer');
        ci.initialize();
        ci.setValue('name', name);
        ci.setValue('install_status', status);
        return ci.insert();
    }

    function newAssetFor(ciId) {
        // So legt ServiceNow Assets aus CIs an: immer zuerst «In use»
        var asset = new GlideRecord('alm_hardware');
        asset.initialize();
        asset.setValue('ci', ciId);
        asset.setValue('install_status', IN_USE);
        return asset.insert();
    }

    function load(id) {
        var gr = new GlideRecord('alm_hardware');
        gr.get(id);
        return gr;
    }

    function adminId() {
        var user = new GlideRecord('sys_user');
        user.get('user_name', 'admin');
        return user.getUniqueValue();
    }

    describe('Business Rule «ITAM: Lifecycle-Status Hardware-Asset»', function () {
        it('übernimmt beim Anlegen den Status «In Stock» vom CI', function () {
            var asset = load(newAssetFor(newComputerCi('ATF-NB-LAGER', IN_STOCK)));
            expect(asset.getValue('install_status')).toBe(IN_STOCK);
            expect(asset.getValue('substatus')).toBe('available');
        });

        it('übernimmt beim Anlegen den Status «Retired» vom CI', function () {
            var asset = load(newAssetFor(newComputerCi('ATF-NB-ALT', RETIRED)));
            expect(asset.getValue('install_status')).toBe(RETIRED);
        });

        it('setzt bei der Zuweisung aus dem Lager das Zuweisungsdatum und leert den Unterstatus', function () {
            var asset = load(newAssetFor(newComputerCi('ATF-NB-NEU', IN_STOCK)));
            asset.setValue('install_status', IN_USE);
            asset.setValue('assigned_to', adminId());
            asset.update();
            asset = load(asset.getUniqueValue());
            expect(asset.getValue('install_status')).toBe(IN_USE);
            expect(asset.getValue('assigned_to')).toBe(adminId());
            expect(asset.assigned.nil()).toBe(false);
            expect(asset.substatus.nil()).toBe(true);
        });
    });

    describe('Standardverhalten der Plattform (Grundlage für den Flow)', function () {
        it('löscht die Zuweisung, solange ein Gerät im Lager ist', function () {
            var asset = load(newAssetFor(newComputerCi('ATF-NB-ZUWEISUNG', IN_STOCK)));
            asset.setValue('assigned_to', adminId());
            asset.update();
            asset = load(asset.getUniqueValue());
            expect(asset.getValue('install_status')).toBe(IN_STOCK);
            expect(asset.assigned_to.nil()).toBe(true);
        });
    });
})(outputs, steps, params, stepResult, assertEqual);

jasmine.getEnv().execute();
