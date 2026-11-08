const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const { compatibilityManifest } = require('./sync-extension-manifest');

const repo = path.resolve(__dirname, '..');
const extension = path.join(repo, 'extension');
const source = JSON.parse(fs.readFileSync(path.join(extension, 'manifest.json'), 'utf8'));
const rootManifest = JSON.parse(fs.readFileSync(path.join(repo, 'manifest.json'), 'utf8'));

function asset(root, file) {
  const resolved = path.resolve(root, file);
  assert.ok(resolved.startsWith(path.resolve(root) + path.sep), `Asset must stay inside extension: ${file}`);
  assert.ok(fs.statSync(resolved).isFile(), `Missing asset: ${file}`);
  return resolved;
}

for (const [name, root, manifest] of [['folder', extension, source], ['root compatibility', repo, rootManifest]]) {
  test(`${name}: manifest, pages, imports and scripts resolve`, () => {
    assert.equal(manifest.manifest_version, 3);
    asset(root, manifest.background.service_worker);
    asset(root, manifest.action.default_popup);
    for (const entry of manifest.content_scripts) {
      for (const file of [...(entry.js || []), ...(entry.css || [])]) asset(root, file);
    }
    for (const page of ['popup.html', 'data.html', 'test.html']) {
      const pageFile = asset(extension, page);
      const html = fs.readFileSync(pageFile, 'utf8');
      for (const match of html.matchAll(/(?:src|href)="([^"#]+)"/g)) asset(path.dirname(pageFile), match[1]);
    }
    const worker = asset(root, manifest.background.service_worker);
    for (const match of fs.readFileSync(worker, 'utf8').matchAll(/importScripts\('([^']+)'\)/g)) asset(path.dirname(worker), match[1]);
    for (const file of fs.readdirSync(extension).filter(f => f.endsWith('.js'))) {
      new vm.Script(fs.readFileSync(path.join(extension, file), 'utf8'), {filename:file});
    }
  });

  test(`${name}: popup opens the test and export pages beside itself`, async () => {
    class Element {
      constructor(tag) { this.tag = tag; this.children = []; this.style = {}; }
      replaceChildren(...children) { this.children = children; }
      append(...children) { this.children.push(...children); }
    }
    const nodes = new Map();
    const opened = [];
    const state = {participant:'P02', lastLabel:'normal', textType:'fixed', sessions:{}, sites:{'chatgpt.com':true}};
    const sandbox = {
      console, URL, location:{href:`chrome-extension://test-id/${manifest.action.default_popup}`},
      setInterval:()=>1, clearInterval:()=>{},
      Option:class { constructor(text,value) { this.text=text;this.value=value; } },
      document:{getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id);},createElement:tag=>new Element(tag)},
      chrome:{storage:{local:{get:async()=>structuredClone(state),set:async()=>{}},onChanged:{addListener:()=>{}}},
              runtime:{sendMessage:async()=>({ok:true})},tabs:{create:async options=>opened.push(options.url)}},
    };
    sandbox.self = sandbox;
    const context = vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(path.join(extension,'common.js'),'utf8'),context);
    vm.runInContext(fs.readFileSync(path.join(extension,'popup.js'),'utf8'),context);
    await new Promise(resolve=>setImmediate(resolve));
    await nodes.get('data').onclick();
    const button = nodes.get('test').children.find(e=>e.textContent==='Run test');
    assert.ok(button, 'Collector self-test button is available');
    await button.onclick();
    const prefix = manifest.action.default_popup.slice(0, manifest.action.default_popup.lastIndexOf('/')+1);
    assert.deepEqual(opened,[`chrome-extension://test-id/${prefix}data.html`,`chrome-extension://test-id/${prefix}test.html`]);
  });

  test(`${name}: worker records, stops and removes a synthetic session without losing existing storage`, async () => {
    const state = {sessions:{legacy:{uid:'legacy',keystrokes:10}},counters:{P02:7},ev_legacy:[{key:'old'}]};
    let onInstalled, onMessage;
    const storage = {
      get:async keys=>{
        if(keys===null)return structuredClone(state);
        const selected=typeof keys==='string'?[keys]:keys;
        return structuredClone(Object.fromEntries(selected.map(k=>[k,state[k]])));
      },
      set:async values=>Object.assign(state,structuredClone(values)),
      remove:async keys=>{for(const key of keys)delete state[key];},
    };
    const sandbox={console,chrome:{storage:{local:storage},runtime:{onInstalled:{addListener:f=>onInstalled=f},onMessage:{addListener:f=>onMessage=f}}}};
    sandbox.self=sandbox;
    const context=vm.createContext(sandbox);
    const worker=path.join(root,manifest.background.service_worker);
    sandbox.importScripts=file=>vm.runInContext(fs.readFileSync(asset(path.dirname(worker),file),'utf8'),context);
    vm.runInContext(fs.readFileSync(worker,'utf8'),context);
    await onInstalled();
    assert.equal(state.sessions.legacy.keystrokes,10);
    const send=message=>new Promise(resolve=>onMessage(message,{},resolve));
    const started=await send({type:'start',participant_id:'P02',label:'normal',alertness:4});
    assert.equal(started.ok,true);
    assert.equal(started.res.session_id,'S8');
    const uid=started.res.uid;
    const saved=await send({type:'rows',uid,rows:[{event:'down',key:'a',press_id:'1'},{event:'up',key:'a',press_id:'1'}]});
    assert.equal(saved.ok,true);
    assert.equal(state.sessions[uid].keystrokes,1);
    const chunk=Object.keys(state).find(k=>k.startsWith(`ev_${uid}_`));
    assert.equal(state[chunk][0].participant_id,'P02');
    await send({type:'stop'});
    assert.equal(state.active,null);
    assert.ok(state.sessions[uid].end);
    await send({type:'delete',uid});
    assert.equal(state.sessions[uid],undefined);
    assert.equal(state[chunk],undefined);
    assert.equal(state.sessions.legacy.keystrokes,10);
    assert.deepEqual(state.ev_legacy,[{key:'old'}]);
  });
}

test('root compatibility manifest matches the authoritative folder manifest', () => {
  assert.deepEqual(rootManifest, compatibilityManifest(source));
});
