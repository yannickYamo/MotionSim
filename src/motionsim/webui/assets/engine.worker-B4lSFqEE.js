(function(){"use strict";const o="https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";let i=null;async function r(n,e){const a=s=>postMessage({progress:s});a("Fetching the Python runtime from cdn.jsdelivr.net"),importScripts(`${o}pyodide.js`);const t=await loadPyodide({indexURL:o});a("Loading the numerical libraries"),await t.loadPackage(["numpy","scipy","pydantic","pyyaml"]),a("Loading the engine");const c=await(await fetch(n)).arrayBuffer();t.unpackArchive(new Uint8Array(c),"zip",{extractDir:"/engine"}),t.runPython(`
import sys
sys.path.insert(0, "/engine")
from pathlib import Path
from motionsim import page
_workspace = page.Workspace(Path("/devices"))
def _call(route, payload):
    return page.call(route, payload, _workspace)
`);const p=t.globals.get("_call");i=(s,d)=>p(s,d);for(const s of e)i("/api/device",JSON.stringify(s));postMessage({ready:!0})}onmessage=n=>{const e=n.data;if(e.start){r(e.start.engineUrl,e.start.devices).catch(t=>postMessage({failed:String(t?.message??t)}));return}const a=JSON.parse(i(e.route,e.payload));postMessage({id:e.id,status:a.status,body:a.body})}})();
