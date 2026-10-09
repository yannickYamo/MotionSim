// The engine, running in the browser. This worker loads a Python runtime, the numerical
// libraries and the motionsim package itself, then answers the same requests the local
// server answers, by calling the same Python functions. No second implementation exists.

declare function importScripts(...urls: string[]): void;
declare function loadPyodide(options: { indexURL: string }): Promise<any>;

const RUNTIME = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";

let call: ((route: string, payload: string) => string) | null = null;

async function start(engineUrl: string, devices: { name: string; text: string }[]): Promise<void> {
  const say = (progress: string) => postMessage({ progress });
  say("Fetching the Python runtime");
  importScripts(`${RUNTIME}pyodide.js`);
  const py = await loadPyodide({ indexURL: RUNTIME });
  say("Loading the numerical libraries");
  await py.loadPackage(["numpy", "scipy", "pydantic", "pyyaml"]);
  say("Loading the engine");
  const archive = await (await fetch(engineUrl)).arrayBuffer();
  py.unpackArchive(new Uint8Array(archive), "zip", { extractDir: "/engine" });
  py.runPython(`
import sys
sys.path.insert(0, "/engine")
from pathlib import Path
from motionsim import page
_workspace = page.Workspace(Path("/devices"))
def _call(route, payload):
    return page.call(route, payload, _workspace)
`);
  const python = py.globals.get("_call");
  call = (route, payload) => python(route, payload);
  // Device files the user added on an earlier visit live in this browser only.
  for (const device of devices) call("/api/device", JSON.stringify(device));
  postMessage({ ready: true });
}

onmessage = (event: MessageEvent) => {
  const message = event.data;
  if (message.start) {
    start(message.start.engineUrl, message.start.devices).catch((error) =>
      postMessage({ failed: String(error?.message ?? error) }),
    );
    return;
  }
  const answer = JSON.parse(call!(message.route, message.payload));
  postMessage({ id: message.id, status: answer.status, body: answer.body });
};
