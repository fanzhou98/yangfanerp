const fs=require('fs');
const src=fs.readFileSync('web/forms.js','utf8');
const wheel=src.split('\n').filter(l=>l.includes("addEventListener('wheel'"));
if(!wheel.length) throw new Error('global wheel guard missing');
if(!wheel[0].includes('passive:false')) throw new Error('wheel guard must be non-passive');
if(!wheel[0].includes('preventDefault')) throw new Error('wheel guard must preventDefault');
console.log('Number wheel guard is non-passive and prevents default.');
