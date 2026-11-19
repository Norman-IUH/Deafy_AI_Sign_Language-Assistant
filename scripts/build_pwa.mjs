import {readFile,writeFile,readdir,rm} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const scope=process.argv[2]==='--mobile-test'?'/mobile-test/':'/';
const testing=scope!=='/';
const root=fileURLToPath(new URL(testing?'../.tools/mobile-test-www/':process.argv[2]==='--gps'?'../iPhone_GPS/www/':'../Android_App/www/',import.meta.url));
if(testing){
  const manifestPath=path.join(root,'manifest.webmanifest');
  const manifest=JSON.parse(await readFile(manifestPath,'utf8'));
  Object.assign(manifest,{id:scope,scope,start_url:scope+'?source=pwa',name:'Deafy Mobile Test',short_name:'Deafy Mobile Test'});
  for(const icon of manifest.icons) icon.src=scope+icon.src.replace(/^\//,'');
  await writeFile(manifestPath,JSON.stringify(manifest));
  const indexPath=path.join(root,'index.html');
  const index=await readFile(indexPath,'utf8');
  await writeFile(indexPath,index.replaceAll('SignAssist','Deafy Mobile Test').replaceAll('Sign Assist','Deafy Mobile Test'));
}
if(!testing){
  const generatedTasks=path.resolve(root,'mobile/tasks');
  if(!generatedTasks.startsWith(path.resolve(root)+path.sep))throw Error('Invalid generated assets path');
  await rm(generatedTasks,{recursive:true,force:true});
}
async function list(folder){
  const files=[];
  for(const entry of await readdir(folder,{withFileTypes:true})){
    const target=path.join(folder,entry.name);
    if(entry.isDirectory())files.push(...await list(target));else if(entry.name!=='sw.js')files.push(target);
  }
  return files;
}
const files=await list(root),hash=createHash('sha256');
const template=await readFile(new URL('../Android_App/public/sw.js',import.meta.url),'utf8');
hash.update(template).update(scope);
for(const file of files.sort())hash.update(await readFile(file));
const urls=files.map(file=>path.relative(root,file).split(path.sep).join('/'))
  .filter(file=>!file.startsWith('mobile/tasks/') && !file.startsWith('assets/diagnostic-detector-')).map(file=>scope+(file==='index.html'?'':file));
await writeFile(path.join(root,'sw.js'),template.replace('__BUILD_ID__',hash.digest('hex').slice(0,16)).replace('__STATIC_FILES__',JSON.stringify(urls)).replace('__SCOPE__',JSON.stringify(scope)).replace('__CACHE_PREFIX__',JSON.stringify(testing?'deafy-mobile-test-':'signassist-')));
console.log(`PWA: ${urls.length} public assets; API/location/audio excluded.`);

