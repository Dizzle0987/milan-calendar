"""Execute the actual page renderer with a minimal local DOM, without network."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js needed for browser-renderer regression")
def test_page_shows_possible_candidates_with_official_links_and_no_duplicates():
    html = (Path(__file__).parents[1] / "index.html").read_text()
    functions = html[html.index("      function broadcastText("):html.index("      function renderMatchCenter(")]
    script = r'''
const assert = require("node:assert/strict");
function node() { return {children: [], textContent: "", append(x) {this.children.push(x);}}; }
const document = {createElement: node, createTextNode: text => ({textContent: text, children: []})};
function make() { return node(); }
function text(n) { return n.textContent + n.children.map(text).join(""); }
function links(n) { return [...(n.href ? [n.href] : []), ...n.children.flatMap(links)]; }
'''+functions+r'''
const cbc = {broadcaster: "CBC Sport", country: "Azerbaijan", country_code: "AZ", status: "POSSIBLE_FREE", match_confirmed: false, free_or_pay: "free", watch_url: "https://cbcsport.az/live/"};
const m4 = {broadcaster: "M4 Sport", country: "Ungheria", country_code: "HU", status: "UNKNOWN", match_confirmed: true, access: "unknown", watch_url: "https://mediaklikk.hu/elo/mtv4live"};
const event = {broadcast_it: "Sky Sport e NOW", broadcast_notes_compact: true, broadcast_italy_tbc: true, foreign_possible_broadcasts: [cbc], broadcast_candidates: [cbc, m4,
  {...m4, broadcaster: "Paid", access: "paid"},
  {...m4, broadcaster: "Unconfirmed", match_confirmed: false},
  {...m4, broadcaster: "Unknown country", country_code: "ZZ"},
  {...m4, broadcaster: "YouTube", watch_url: "https://www.youtube.com/watch?v=x"}]};
const before = JSON.stringify(event);
const result = broadcastElement(event), rendered = text(result);
assert.ok(!rendered.includes("CBC Sport"));
assert.ok(rendered.includes("M4 Sport — Ungheria — VPN · TV confermata · Streaming web da verificare"));
assert.ok(rendered.indexOf("Sky Sport e NOW") < rendered.indexOf("M4 Sport"));
for (const forbidden of ["Paid", "Unconfirmed", "Unknown country", "YouTube", "Streaming web gratuito", "UNKNOWN", "POSSIBLE_FREE"]) assert.ok(!rendered.includes(forbidden));
assert.deepEqual(links(result), [m4.watch_url]);
assert.equal(JSON.stringify(event), before);
cbc.match_confirmed = true;
assert.equal((text(broadcastElement(event)).match(/CBC Sport/g) || []).length, 1);
assert.equal(text(broadcastElement({broadcast_it: "DAZN"})), "Dove vederla: 🇮🇹 DAZN🌍 In chiaro all'estero — Da confermare");
'''
    subprocess.run([shutil.which("node"), "-e", script], check=True, capture_output=True, text=True)
