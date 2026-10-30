import json,base64,urllib.request,sys,pathlib
STYLE="Flat, calm editorial illustration, soft muted colors, simple shapes, white background, no text, no letters, no numbers, no logos, no brand names, no real company buildings or products."
P={
"title":"A shield protecting a laptop and a server from a shadowy hacker silhouette, cyber security concept.",
"method":"A magnifying glass over official documents and a newspaper, fact checking concept.",
"asahi":"A beverage distribution warehouse with stacked crates and a delivery truck, while a computer screen shows a red warning lock symbol.",
"keio":"A generic commuter train running normally beside an office server rack with a red warning lock icon.",
"tein":"A generic auto parts workshop with car suspension springs on a table, and an office computer showing a locked file icon.",
"capcom":"A game controller next to a smartphone showing a user account icon with a broken padlock.",
"idcf":"Rows of cloud data center servers, a few of them dark and locked with chains, engineers checking them.",
"estore":"An online shopping cart on a laptop screen with an envelope icon leaking data packets.",
"nichirei":"A frozen food cold storage warehouse with forklifts and pallets, and a control monitor showing a pause icon.",
"gmo":"A trading chart on a monitor connected to a virtual cloud server, with a warning shield icon.",
"common":"Three steps: unplugging a network cable, reporting to police and experts, publishing a notice board, shown as a simple flow.",
"personal":"A person holding a smartphone, ignoring a suspicious message with a hook icon, and setting different keys for different doors.",
"end":"A cozy countryside landscape with fields and a small house, peaceful evening.",
}
out=pathlib.Path('/tmp/claude-0/hack/img')
for k,v in P.items():
    f=out/f'{k}.png'
    if f.exists(): continue
    body={"model":"gpt-image-1-mini","prompt":v+" "+STYLE,"size":"1024x1024","quality":"low","n":1}
    req=urllib.request.Request("https://api.openai.com/v1/images/generations",data=json.dumps(body).encode(),headers={"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=300) as r: d=json.load(r)
    except urllib.error.HTTPError as e:
        print(k,'ERR',e.code,e.read()[:200]); continue
    f.write_bytes(base64.b64decode(d['data'][0]['b64_json'])); print(k,'ok',f.stat().st_size)
