// Only public app files are cached. Never cache API, authentication, location or audio.
const PREFIX=__CACHE_PREFIX__;
const CACHE=PREFIX+'__BUILD_ID__';
const SCOPE=__SCOPE__;
const FILES=__STATIC_FILES__;
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(FILES))));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
  for(const name of await caches.keys())if(name.startsWith(PREFIX)&&name!==CACHE)await caches.delete(name);
  await self.clients.claim();
})()));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==self.location.origin||!url.pathname.startsWith(SCOPE)||url.pathname==='/api'||url.pathname.startsWith('/api/')||url.pathname==='/ws'||!FILES.includes(url.pathname)&&event.request.mode!=='navigate')return;
  event.respondWith((async()=>{
    try{return await fetch(event.request);}catch{
      return await (await caches.open(CACHE)).match(event.request,{ignoreSearch:true})||(event.request.mode==='navigate'?await (await caches.open(CACHE)).match(SCOPE):null)||Response.error();
    }
  })());
});
