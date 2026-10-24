// guarddog-mcp smoke (npm test)
const fs = require('fs');
const path = require('path');
const pkg = require('../package.json');
for (const f of ['bin/guarddog-mcp.js', 'lib/atg/mcp_server/server.py',
                 'lib/atg/api/main.py']) {
  if (!fs.existsSync(path.join(__dirname, '..', f))) {
    console.error('MISSING: ' + f);
    process.exit(1);
  }
}
const src = fs.readFileSync(
    path.join(__dirname, '../bin/guarddog-mcp.js'), 'utf8')
    .replace(/^#!.*\n/m, '');
new Function(src);  // 语法校验(不执行)
if (!pkg.bin['guarddog-mcp']) {
  console.error('bin entry missing');
  process.exit(1);
}
console.log('smoke ok:', pkg.name, pkg.version);
