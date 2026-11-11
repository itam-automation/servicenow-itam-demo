/**
 * Deployer for the ITAM Toolkit bundle (toolkit/build_bundle.py), run in the browser console of an
 * admin session on a classic UI page (window.g_ck must exist). Upserts every record of the bundle
 * through the Table API into the current application and update set.
 *
 * Before running: switch the current application to «ITAM Toolkit» and select its update set.
 * The script refuses to run otherwise.
 *
 *   1. python3 toolkit/build_bundle.py --out bundle.json
 *   2. paste this file into the console
 *   3. const bundle = await pickBundle();          // file dialog, choose bundle.json
 *   4. await deployBundle(bundle, 'ITAM Toolkit 0.1.0');
 *   5. await applyLayouts(bundle.layouts);
 *
 * The ATF step scripts are set with a background script (sys_variable_value is not writable through
 * the Table API); see setAtfScripts().
 */
/* eslint-disable no-console */
const api = async (method, path, body) => {
    const response = await fetch(path, {
        method,
        headers: {'X-UserToken': window.g_ck, Accept: 'application/json', 'Content-Type': 'application/json'},
        body: body ? JSON.stringify(body) : undefined
    });
    const text = await response.text();
    let json;
    try {
        json = JSON.parse(text);
    } catch (e) {
        json = text;
    }
    return {status: response.status, body: json};
};

const q = async (table, query, fields, limit = 200) => {
    const r = await api('GET', `/api/now/table/${table}?sysparm_query=${encodeURIComponent(query)}` +
        `&sysparm_fields=${fields}&sysparm_limit=${limit}`);
    return r.status === 200 ? r.body.result : `HTTP ${r.status}`;
};

const pickBundle = () => new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.onchange = async () => resolve(JSON.parse(await input.files[0].text()));
    input.click();
});

async function context() {
    const app = (await api('GET', '/api/now/ui/concoursepicker/application')).body.result.current;
    const updateSet = (await api('GET', '/api/now/ui/concoursepicker/updateset')).body.result.current;
    const scope = (await q('sys_scope', 'sys_id=' + app, 'scope', 1))[0].scope;
    return {app, scope, updateSet: updateSet.name};
}

async function deployBundle(bundle, updateSetPrefix) {
    const ctx = await context();
    if (!ctx.scope.endsWith('_itamkit') || !String(ctx.updateSet).startsWith(updateSetPrefix)) {
        return [`ABORT: current application/update set is ${ctx.scope} / ${ctx.updateSet}`];
    }
    const refs = {};
    const cache = {};
    const log = [];
    const resolve = async (value) => {
        if (typeof value !== 'string') return value;
        let s = value.replace(/\{\{P\}\}/g, ctx.scope).replace(/\{\{APP\}\}/g, ctx.app);
        for (const m of [...s.matchAll(/\{\{(ref|lookup):([^}]*)\}\}/g)]) {
            let v;
            if (m[1] === 'ref') {
                v = refs[m[2]];
            } else {
                if (!(m[2] in cache)) {
                    const i = m[2].indexOf(':');
                    const r = await q(m[2].slice(0, i), m[2].slice(i + 1), 'sys_id', 1);
                    cache[m[2]] = Array.isArray(r) && r.length ? r[0].sys_id : null;
                }
                v = cache[m[2]];
            }
            if (!v) throw new Error('unresolved ' + m[0]);
            s = s.split(m[0]).join(v);
        }
        return s;
    };
    for (const rec of bundle.records) {
        const label = rec.key || rec.table + ' ' + Object.values(rec.match).join('/');
        try {
            const match = {};
            for (const [k, v] of Object.entries(rec.match)) match[k] = await resolve(v);
            const values = {};
            for (const [k, v] of Object.entries(rec.values)) values[k] = await resolve(v);
            const query = Object.entries(match).map(([k, v]) => k + '=' + v).join('^');
            const found = await q(rec.table, query, 'sys_id', 2);
            if (!Array.isArray(found)) throw new Error('query failed: ' + found);
            const r = found.length
                ? await api('PATCH', `/api/now/table/${rec.table}/${found[0].sys_id}?sysparm_fields=sys_id`, values)
                : await api('POST', `/api/now/table/${rec.table}?sysparm_fields=sys_id`, {...match, ...values});
            if (r.status >= 300) throw new Error('HTTP ' + r.status + ' ' + JSON.stringify(r.body).slice(0, 300));
            if (rec.key) refs[rec.key] = r.body.result.sys_id;
            log.push((found.length ? 'upd ' : 'new ') + label);
        } catch (e) {
            log.push('ERR ' + label + ': ' + (e.message || e));
        }
    }
    return log;
}

/** Form, related list and list layouts of the app's own tables (default view). */
async function applyLayouts(layouts) {
    const ctx = await context();
    const sub = (s) => s.split('{{P}}').join(ctx.scope);
    const del = (table, id) => api('DELETE', `/api/now/table/${table}/${id}`);
    const log = [];
    for (const [rawTable, spec] of Object.entries(layouts.forms)) {
        const table = sub(rawTable);
        const sections = await q('sys_ui_section', `name=${table}^view=Default view^captionISEMPTY`, 'sys_id', 1);
        const sectionId = sections.length ? sections[0].sys_id
            : (await api('POST', '/api/now/table/sys_ui_section?sysparm_fields=sys_id',
                {name: table, view: 'Default view', caption: ''})).body.result.sys_id;
        for (const e of await q('sys_ui_element', 'sys_ui_section=' + sectionId, 'sys_id', 200)) await del('sys_ui_element', e.sys_id);
        let position = 0;
        for (const field of spec.fields) {
            const element = {sys_ui_section: sectionId, element: field, position: String(position++)};
            if (field.startsWith('.')) element.type = field;
            await api('POST', '/api/now/table/sys_ui_element', element);
        }
        if (spec.related.length) {
            const lists = await q('sys_ui_related_list', `name=${table}^view=Default view`, 'sys_id', 1);
            const listId = lists.length ? lists[0].sys_id
                : (await api('POST', '/api/now/table/sys_ui_related_list?sysparm_fields=sys_id',
                    {name: table, view: 'Default view'})).body.result.sys_id;
            for (const e of await q('sys_ui_related_list_entry', 'list_id=' + listId, 'sys_id', 50)) await del('sys_ui_related_list_entry', e.sys_id);
            let p = 0;
            for (const related of spec.related) {
                await api('POST', '/api/now/table/sys_ui_related_list_entry', {list_id: listId, related_list: sub(related), position: String(p++)});
            }
        }
        log.push('form ' + table);
    }
    for (const l of layouts.lists) {
        const table = sub(l.table);
        const parent = sub(l.parent || '');
        const found = await q('sys_ui_list', `name=${table}^view=Default view^` + (parent ? `parent=${parent}` : 'parentISEMPTY'), 'sys_id', 1);
        const listId = found.length ? found[0].sys_id
            : (await api('POST', '/api/now/table/sys_ui_list?sysparm_fields=sys_id',
                {name: table, view: 'Default view', ...(parent ? {parent} : {})})).body.result.sys_id;
        for (const e of await q('sys_ui_list_element', 'list_id=' + listId, 'sys_id', 100)) await del('sys_ui_list_element', e.sys_id);
        let p = 0;
        for (const column of l.columns) {
            await api('POST', '/api/now/table/sys_ui_list_element', {list_id: listId, element: sub(column), position: String(p++)});
        }
        log.push('list ' + table + (parent ? ' in ' + parent : ''));
    }
    return log;
}

/** Runs a background script (Scripts - Background) in the given scope and returns the output text. */
async function runBackground(script, scopeSysId) {
    const form = new URLSearchParams({script, runscript: 'Run script', sysparm_ck: window.g_ck, sys_scope: scopeSysId,
        record_for_rollback: 'on', quota_managed_transaction: 'on'});
    const r = await fetch('/sys.scripts.do', {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: form.toString()});
    const div = document.createElement('div');
    div.innerHTML = await r.text();
    return div.innerText;
}

/** Sets the test script of the single «Run Server Side Script» step of each ATF test. */
async function setAtfScripts(bundle) {
    const scripts = bundle.records.filter((r) => r.table === 'sys_variable_value' &&
        r.match.variable === '989d9e235324220002c6435723dc3484');
    const tests = bundle.records.filter((r) => r.table === 'sys_atf_test').map((r) => r.match.name);
    const data = tests.map((name, i) => [name, scripts[i].values.value]);
    const script = 'var data = ' + JSON.stringify(data) + ';\n' +
        "data.forEach(function (d) { var s = new GlideRecord('sys_atf_step'); s.addQuery('test.name', d[0]); " +
        "s.addQuery('order', 1); s.query(); if (!s.next()) return; s.inputs.jasmine_version = '3.1'; " +
        "s.inputs.script = d[1]; s.update(); gs.info('step ok ' + d[0]); });";
    return runBackground(script, 'global');
}

console.log('ITAM Toolkit deployer loaded: pickBundle, deployBundle, applyLayouts, setAtfScripts');
