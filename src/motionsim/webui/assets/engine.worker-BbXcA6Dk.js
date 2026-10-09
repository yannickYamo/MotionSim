(function(){"use strict";const o="https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";let i=null;async function r(n,t){const a=s=>postMessage({progress:s});a("Fetching the Python runtime"),importScripts(`${o}pyodide.js`);const e=await loadPyodide({indexURL:o});a("Loading the numerical libraries"),await e.loadPackage(["numpy","scipy","pydantic","pyyaml"]),a("Loading the engine");const c=await(await fetch(n)).arrayBuffer();e.unpackArchive(new Uint8Array(c),"zip",{extractDir:"/engine"}),e.runPython(`
import sys
sys.path.insert(0, "/engine")
from pathlib import Path
from motionsim import page
_workspace = page.Workspace(Path("/devices"))
def _call(route, payload):
    return page.call(route, payload, _workspace)
`);const p=e.globals.get("_call");i=(s,d)=>p(s,d);for(const s of t)i("/api/device",JSON.stringify(s));postMessage({ready:!0})}onmessage=n=>{const t=n.data;if(t.start){r(t.start.engineUrl,t.start.devices).catch(e=>postMessage({failed:String(e?.message??e)}));return}const a=JSON.parse(i(t.route,t.payload));postMessage({id:t.id,status:a.status,body:a.body})}})();
