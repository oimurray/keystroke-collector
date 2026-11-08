#!/usr/bin/env node
// The folder manifest is authoritative. The root manifest keeps existing unpacked installs working.
const fs = require('node:fs');
const path = require('node:path');

function compatibilityManifest(source) {
  const manifest = structuredClone(source);
  manifest.background.service_worker = `extension/${source.background.service_worker}`;
  manifest.action.default_popup = `extension/${source.action.default_popup}`;
  for (const script of manifest.content_scripts || []) {
    for (const kind of ['js', 'css']) {
      if (script[kind]) script[kind] = script[kind].map(file => `extension/${file}`);
    }
  }
  return manifest;
}

if (require.main === module) {
  const repo = path.resolve(__dirname, '..');
  const source = JSON.parse(fs.readFileSync(path.join(repo, 'extension', 'manifest.json'), 'utf8'));
  fs.writeFileSync(path.join(repo, 'manifest.json'), JSON.stringify(compatibilityManifest(source), null, 2) + '\n');
  console.log('Updated root compatibility manifest from extension/manifest.json.');
}

module.exports = { compatibilityManifest };
