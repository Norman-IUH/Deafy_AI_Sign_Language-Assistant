import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const root=new URL('../Android_App/www/',import.meta.url);

test('compiled service worker contains only public static files and bypasses private requests',()=>{
  const handlers={};
  const context=vm.createContext({self:{location:{origin:'https://example.test'},addEventListener:(type,fn)=>handlers[type]=fn},URL});
  vm.runInContext(fs.readFileSync(new URL('sw.js',root),'utf8'),context);
  const files=vm.runInContext('FILES',context);
  assert(files.includes('/')&&files.includes('/icons/signassist-192.png'));
  for(const file of files){assert(!/api\/|\.env|\.pth|\.sqlite/.test(file));assert(fs.existsSync(new URL(file==='/'?'index.html':file.slice(1),root)));}
  let intercepted=0;
  for(const [url,method] of [['/api/state','GET'],['/api/location','GET'],['/api','GET'],['/ws','GET'],['/api/pi/audio/private','GET'],['/','POST'],['https://other.test/','GET']]){
    handlers.fetch({request:{url:new URL(url,'https://example.test').href,method,mode:'navigate'},respondWith(){intercepted++;}});
  }
  assert.equal(intercepted,0);
  const manifest=JSON.parse(fs.readFileSync(new URL('manifest.webmanifest',root)));
  for(const icon of manifest.icons){const bytes=fs.readFileSync(new URL(icon.src.slice(1),root));const size=Number(icon.sizes.split('x')[0]);assert.equal(bytes.readUInt32BE(16),size);assert.equal(bytes.readUInt32BE(20),size);}
});
