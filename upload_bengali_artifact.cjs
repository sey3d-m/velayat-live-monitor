'use strict';
// Upload an immutable Actions v4 artifact while source workflow is still running.
const fs = require('node:fs');
const path = require('node:path');
const { uploadArtifact } = require('./.bengali-tools/node_modules/@actions/artifact');

async function main() {
  const [name, folder] = process.argv.slice(2);
  if (!/^bengali-clip-\d+-[12]$/.test(name || '')) throw Error('invalid artifact name');
  const base = path.resolve(folder);
  const manifest = JSON.parse(fs.readFileSync(path.join(base, 'manifest.json'), 'utf8'));
  if (manifest.count !== 1 || ![1, 2].includes(manifest.clip_index))
    throw Error('invalid single-clip manifest');
  const video = path.join(base, 'source_' + String(manifest.clip_index).padStart(2, '0') + '.mp4');
  if (!fs.existsSync(video) || fs.statSync(video).size < 10_000)
    throw Error('missing clip MP4');
  const result = await uploadArtifact(name, [path.join(base, 'manifest.json'), video], base,
                                      {retentionDays: 1, compressionLevel: 0});
  console.log('Bengali artifact uploaded, id=' + result.id);
}
main().catch(err => { console.error(err); process.exitCode = 1; });
