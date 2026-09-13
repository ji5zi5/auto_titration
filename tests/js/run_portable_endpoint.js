'use strict';
const fs = require('node:fs');
const zlib = require('node:zlib');
const endpoint = require('../../website/portable-endpoint.js');
const artifact = JSON.parse(zlib.gunzipSync(fs.readFileSync(process.argv[2])));
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(c => ({ name: c.name, result: endpoint.predict(artifact, c.rows, c.type), candidates: endpoint.candidates(c.rows).length }))));
