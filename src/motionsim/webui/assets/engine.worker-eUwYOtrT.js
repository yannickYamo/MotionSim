(function(){let e=null,t=null;async function n({engineUrl:n,runtimeUrl:r,parts:i}){let a=(e,t)=>postMessage({progress:e,stage:t,of:3});a(`Starting the Python runtime`,1),importScripts(`${r}pyodide.js`);let o=await loadPyodide({indexURL:r,lockFileURL:`${r}pyodide-lock.json`});a(`Fetching the numerical libraries from cdn.jsdelivr.net`,2);let s=[];await o.loadPackage([`numpy`,`scipy`,`pydantic`,`pyyaml`],{checkIntegrity:!0,errorCallback:e=>s.push(e)});try{o.runPython(`import numpy, scipy, scipy.optimize, scipy.signal, scipy.sparse, pydantic, yaml`)}catch(e){let t=e instanceof Error?e.message.split(`
`).pop()??``:String(e);throw Error(`the numerical libraries did not all arrive (${[t,...s].join(`; `)})`,{cause:e})}a(`Loading the engine`,3);let c=await(await fetch(n)).arrayBuffer();o.unpackArchive(new Uint8Array(c),`zip`,{extractDir:`/engine`}),o.runPython(`
import sys
sys.path.insert(0, "/engine")
from pathlib import Path
from motionsim import page
_workspace = page.Workspace(Path("/devices"))
def _call(route, payload):
    return page.call(route, payload, _workspace)
def _stream(route, payload):
    return page.stream_call(route, payload, _workspace)
def _next(lines):
    return next(lines, None)
def _close(lines):
    lines.close()
`);let l=o.globals.get(`_call`);e=(e,t)=>l(e,t);let[u,d,f]=[`_stream`,`_next`,`_close`].map(e=>o.globals.get(e));t=(e,t)=>{let n=u(e,t),r=()=>n.destroy?.();return{next:()=>{let e=d(n);return e??r(),e??null},close:()=>{f(n),r()}}};for(let t of i)e(t.route,JSON.stringify(t.body));postMessage({ready:!0})}function r(t){try{if(!e)throw Error(`the engine has not started`);let n=JSON.parse(e(t.route,t.payload));return{id:t.id,status:n.status,body:n.body}}catch(e){let n=e instanceof Error?e.message:String(e);return{id:t.id,status:500,body:{error:`the engine failed: ${n.split(`
`).pop()}`}}}}let i=/* @__PURE__ */ new Set,a=()=>new Promise(e=>setTimeout(e,0));async function o(e){let n=t=>({id:e.id,status:500,body:{error:`the engine failed: ${t}`}});if(!t)return n(`the engine has not started`);let r;try{r=t(e.route,e.payload)}catch(e){return n(e instanceof Error?e.message.split(`
`).pop()??``:String(e))}try{for(;;){if(await a(),i.delete(e.id))return r.close(),{id:e.id,status:499,body:{error:`given up`}};let t=r.next();if(t===null)return n(`the search ended with no answer`);let o=JSON.parse(t);if(!(`probe`in o))return{id:e.id,status:o.status,body:o.body};postMessage({id:e.id,probe:o.probe})}}catch(e){return n(e instanceof Error?e.message.split(`
`).pop()??``:String(e))}}onmessage=e=>{let t=e.data;t.start?n(t.start).catch(e=>postMessage({failed:String(e?.message??e)})):t.cancel===void 0?t.stream?o(t).then(e=>postMessage(e)):postMessage(r(t)):i.add(t.cancel)}})();