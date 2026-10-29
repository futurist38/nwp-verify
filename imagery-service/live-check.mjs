// Network preflight only: no credentials, no deployment, no persisted imagery.
import worker from './worker.mjs';
globalThis.caches={default:{match:async()=>null,put:async()=>{}}};
for(const kind of ['satellite','radar']){
 const r=await worker.fetch(new Request('https://example.workers.dev/latest/'+kind,{headers:{Origin:'https://futurist38.github.io'}}),{IMAGERY_LIMITER:{limit:async()=>({success:true})}},{});
 const data=await r.json();console.log(JSON.stringify({kind,status:r.status,time:data.time,error:data.error,encodedBytes:data.src?.length}));if(!r.ok)process.exitCode=1;
}
