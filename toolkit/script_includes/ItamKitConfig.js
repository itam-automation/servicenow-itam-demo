/**
 * ItamKitConfig: names of the toolkit's tables, properties and events.
 *
 * The scope name contains the instance's vendor prefix (x_<prefix>_itamkit). The
 * scripts never hard-code it: every name is derived from the running scope, so the
 * sources stay identical on every instance.
 */
var ItamKitConfig = Class.create();

ItamKitConfig.scope = function () {
    return gs.getCurrentScopeName();
};

/** ItamKitConfig.table('leaver_case') -> 'x_<prefix>_itamkit_leaver_case' */
ItamKitConfig.table = function (suffix) {
    return ItamKitConfig.scope() + '_' + suffix;
};

/** Column the toolkit adds to the global table asset_task */
ItamKitConfig.outcomeField = function () {
    return ItamKitConfig.scope() + '_return_outcome';
};

ItamKitConfig.prop = function (name, fallback) {
    return gs.getProperty(ItamKitConfig.scope() + '.' + name, fallback);
};

ItamKitConfig.event = function (name) {
    return ItamKitConfig.scope() + '.' + name;
};

ItamKitConfig.role = function (suffix) {
    return ItamKitConfig.scope() + '.' + suffix;
};

/** GlideElement booleans are objects (always truthy); compare their string value. */
ItamKitConfig.isTrue = function (element) {
    const value = String(element);
    return value === 'true' || value === '1';
};

ItamKitConfig.prototype = {
    type: 'ItamKitConfig'
};
