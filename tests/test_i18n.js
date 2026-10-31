'use strict';
const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');
const {compile}=require('../jc_colorlab/static/i18n-core.js');
const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'../jc_colorlab/static/locales/catalog.json'),'utf8'));
test('six complete catalogs with consistent placeholders',()=>{
 assert.deepEqual(catalog.locales,['zh-CN','en','fr','ja','de','ru']);
 assert.equal(new Set(catalog.entries.map(r=>r[0])).size,catalog.entries.length);
 for(const row of catalog.entries){assert.equal(row.length,6);const variables=s=>[...s.matchAll(/\{\d+\}/g)].map(x=>x[0]).sort();for(const v of row){assert.ok(v.trim());assert.deepEqual(variables(v),variables(row[0]));}}
});
for(const locale of catalog.locales.slice(1))test(`${locale}: every catalog entry translates, including dynamic values`,()=>{
 const t=compile(catalog,locale),i=catalog.locales.indexOf(locale);
 for(const row of catalog.entries){const source=row[0].replace(/\{\d+\}/g,'42'),expected=row[i].replace(/\{\d+\}/g,'42');assert.equal(t(source),expected,source);}
 assert.equal(t('sample 240MP / 2GiB'),'sample 240MP / 2GiB');
});
test('Chinese preserves values and text',()=>{assert.equal(compile(catalog,'zh-CN')('376 个数字参考色'),'376 个数字参考色');});
test('nested dynamic labels translate without losing patch count',()=>{assert.equal(compile(catalog,'en')('376 个取样点 · 标记自动识别'),'376 sample points · Markers auto-detected');});
