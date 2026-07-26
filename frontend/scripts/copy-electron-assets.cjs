const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const distElectron = path.join(root, 'dist-electron');
const assetsSrc = path.join(root, 'electron', 'assets');
const assetsDest = path.join(distElectron, 'assets');

fs.mkdirSync(distElectron, { recursive: true });
fs.writeFileSync(path.join(distElectron, 'package.json'), JSON.stringify({ type: 'commonjs' }));

if (fs.existsSync(assetsSrc)) {
  fs.cpSync(assetsSrc, assetsDest, { recursive: true });
  console.log(`Copied tray assets to ${assetsDest}`);
} else {
  console.warn(`Tray assets missing at ${assetsSrc}`);
}
