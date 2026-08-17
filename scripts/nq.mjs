#!/usr/bin/env node
// Andy neon query runner. Reads DATABASE_URL from Moreway | Tasks/.env, executes
// a SQL statement given via stdin (or --sql "..."), prints JSON rows to stdout.
//
// Usage:
//   node nq.mjs --sql "SELECT 1 AS x"
//   echo "SELECT 1" | node nq.mjs
//
// Params via --p "k=v" pairs are substituted with pg-style $1..$N by ordering.

import { readFileSync } from 'node:fs';
import { neon } from '/Users/zander/Claude Code/Moreway/Moreway | Tasks/node_modules/@neondatabase/serverless/index.mjs';

function loadEnv(path) {
  const raw = readFileSync(path, 'utf8');
  for (const line of raw.split('\n')) {
    const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)\s*$/);
    if (!m) continue;
    let v = m[2];
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    if (!(m[1] in process.env)) process.env[m[1]] = v;
  }
}

loadEnv('/Users/zander/Claude Code/Moreway/Moreway | Tasks/.env');

const args = process.argv.slice(2);
let sql = null;
const params = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--sql') { sql = args[++i]; }
  else if (args[i] === '--p') { params.push(args[++i]); }
  else if (args[i] === '--file') { sql = readFileSync(args[++i], 'utf8'); }
}
if (sql === null) {
  sql = readFileSync(0, 'utf8');
}

const dbUrl = process.env.DATABASE_URL;
if (!dbUrl) {
  console.error('DATABASE_URL missing');
  process.exit(2);
}

const client = neon(dbUrl);
try {
  const rows = params.length
    ? await client.query(sql, params)
    : await client(sql);
  process.stdout.write(JSON.stringify(rows, null, 0) + '\n');
} catch (e) {
  console.error('SQL error:', e.message);
  process.exit(1);
}
