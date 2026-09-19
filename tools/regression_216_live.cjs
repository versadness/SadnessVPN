// Opt-in test of the running release. Uses the selected profile, never edits it.
const assert=require('assert/strict');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const base='http://127.0.0.1:45678';
async function post(path){const r=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const b=await r.json();assert(r.ok&&b.ok, 'API operation failed: '+path);}
(async()=>{
 const socket=new WebSocket('ws://127.0.0.1:45678/ws');
 const errors=[],pings=[];let status,initial,ownConnection=false;
 socket.onmessage=e=>{const data=JSON.parse(e.data);if(data.type==='state'){initial=data;status=data.status;}
   if(data.type==='status')status=data.state;
   if(data.type==='log'&&data.tag==='err')errors.push(data.msg);
   if(data.type==='ping')pings.push(data.value);
 };
 try{
  for(let n=0;n<50&&!initial;n++)await pause(100);
  assert(initial&&initial.appVersion==='2.0.16','Release not ready');
  assert.equal(status,'off','Do not interrupt an existing user connection');
  await post('/api/connect');ownConnection=true;
  for(let n=0;n<200&&status!=='on';n++)await pause(100);
  assert.equal(status,'on','Connection did not become ready');
  await pause(24000);
  console.log(JSON.stringify({version:initial.appVersion,connected:status==='on',pingSamples:pings,
    errorCount:errors.length,processLookupErrors:errors.filter(x=>x.includes('failed to search process')).length}));
  assert.equal(status,'on');assert(pings.length>=3);assert.equal(errors.length,0);
 }finally{
  if(ownConnection){await post('/api/disconnect');for(let n=0;n<100&&status!=='off';n++)await pause(100);assert.equal(status,'off');}
  socket.close();
 }
})().catch(e=>{console.error(e.message);process.exitCode=1});
