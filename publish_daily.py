#!/usr/bin/env python3
# Publie la publication Dar Salam Accessoires du jour sur Instagram ET Facebook.
# Autonome : tourne dans GitHub Actions. Idempotent par canal (last.json : {"ig": "YYYY-MM-DD", "fb": "YYYY-MM-DD"}).
# schedule.json : [{jour, date, images:[url raw...], caption_ig, caption_fb}]
import json, os, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone

TOKEN   = os.environ["IG_TOKEN"]            # page access token permanent (sert IG + FB)
IG_ID   = os.environ["IG_USER_ID"]          # instagram business account id
FB_PAGE = os.environ.get("FB_PAGE_ID", "")  # page facebook id
DRY     = os.environ.get("DRY_RUN", "") in ("1", "2")  # 1 = acces ; 2 = acces + conteneur IG test, sans publier
V = "v21.0"
BASE = f"https://graph.facebook.com/{V}/"

def api_post(path, params):
    params = dict(params); params["access_token"] = TOKEN
    req = urllib.request.Request(BASE + path, data=urllib.parse.urlencode(params).encode())
    try:
        return json.load(urllib.request.urlopen(req)), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()[:400]

def api_get(path, params):
    params = dict(params); params["access_token"] = TOKEN
    try:
        return json.load(urllib.request.urlopen(BASE + path + "?" + urllib.parse.urlencode(params))), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()[:400]

if DRY:
    r, e = api_get(IG_ID, {"fields": "username"}); print("IG:", r or e)
    r, e = api_get(FB_PAGE, {"fields": "name"}); print("FB:", r or e)
    if os.environ.get("DRY_RUN") == "1" or not r:
        raise SystemExit(0 if r else 1)
if os.environ.get("DRY_RUN") == "2":
    # test : cree un conteneur Instagram (sans le publier) avec la 1re image du planning
    first = json.load(open("schedule.json", encoding="utf-8"))[0]["images"][0]
    r, e = api_post(f"{IG_ID}/media", {"image_url": first, "is_carousel_item": "true"})
    print("Conteneur test:", r or e)
    if r:
        for _ in range(12):
            st, _e = api_get(r["id"], {"fields": "status_code"}); print("statut:", st)
            if (st or {}).get("status_code") in ("FINISHED", "ERROR"): break
            time.sleep(5)
    raise SystemExit(0)

try:
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Europe/Zurich")).strftime("%Y-%m-%d")
except Exception:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

state = {}
if os.path.exists("last.json"):
    try: state = json.load(open("last.json"))
    except Exception: state = {}

posts = json.load(open("schedule.json", encoding="utf-8"))
todays = [p for p in posts if p["date"] == today]
if not todays:
    print("Aucune publication prevue pour", today); raise SystemExit(0)
p = todays[0]; imgs = p["images"]
cap_ig = p.get("caption_ig") or p.get("caption", ""); cap_fb = p.get("caption_fb") or cap_ig
print(f"Jour {p.get('jour','?')} - {len(imgs)} image(s) - {today}")
errors = []

# ---------- INSTAGRAM ----------
if state.get("ig") == today:
    print("IG: deja publie aujourd'hui, saute.")
else:
    cid = None; err = None
    if len(imgs) == 1:
        r, err = api_post(f"{IG_ID}/media", {"image_url": imgs[0], "caption": cap_ig})
        cid = r["id"] if r else None
    else:
        children = []
        for u in imgs:
            r, e = api_post(f"{IG_ID}/media", {"image_url": u, "is_carousel_item": "true"})
            if e: err = e; break
            children.append(r["id"]); time.sleep(2)
        if not err:
            r, err = api_post(f"{IG_ID}/media", {"media_type": "CAROUSEL", "children": ",".join(children), "caption": cap_ig})
            cid = r["id"] if r else None
    if err or not cid:
        errors.append("IG media: " + (err or "pas de creation_id")); print("IG ERREUR:", err)
    else:
        ready = False
        for _ in range(24):
            r, e = api_get(cid, {"fields": "status_code"})
            st = (r or {}).get("status_code", "")
            if st == "FINISHED": ready = True; break
            if st == "ERROR": break
            time.sleep(5)
        if not ready:
            errors.append("IG conteneur non pret"); print("IG: conteneur non FINISHED")
        else:
            r, err = api_post(f"{IG_ID}/media_publish", {"creation_id": cid})
            if err: errors.append("IG publish: " + err); print("IG ERREUR publish:", err)
            else: state["ig"] = today; print("IG publie:", r)

# ---------- FACEBOOK ----------
if not FB_PAGE:
    print("FB: FB_PAGE_ID absent, canal ignore.")
elif state.get("fb") == today:
    print("FB: deja publie aujourd'hui, saute.")
else:
    if len(imgs) == 1:
        r, err = api_post(f"{FB_PAGE}/photos", {"url": imgs[0], "caption": cap_fb, "published": "true"})
        if err: errors.append("FB photo: " + err); print("FB ERREUR:", err)
        else: state["fb"] = today; print("FB publie:", r)
    else:
        media = []; err = None
        for u in imgs:
            r, e = api_post(f"{FB_PAGE}/photos", {"url": u, "published": "false"})
            if e: err = e; break
            media.append(r["id"]); time.sleep(1)
        if err:
            errors.append("FB upload: " + err); print("FB ERREUR upload:", err)
        else:
            params = {"message": cap_fb}
            for i, mid in enumerate(media):
                params[f"attached_media[{i}]"] = json.dumps({"media_fbid": mid})
            r, err = api_post(f"{FB_PAGE}/feed", params)
            if err: errors.append("FB feed: " + err); print("FB ERREUR feed:", err)
            else: state["fb"] = today; print("FB publie:", r)

# ---------- STORY FACEBOOK (regle : toujours partager en story ; best effort, non bloquant) ----------
if FB_PAGE and state.get("fb") == today and state.get("fb_story") != today:
    r, err = api_post(f"{FB_PAGE}/photos", {"url": imgs[0], "published": "false"})
    if err:
        print("FB story: upload impossible:", err)
    else:
        r2, err2 = api_post(f"{FB_PAGE}/photo_stories", {"photo_id": r["id"]})
        if err2: print("FB story: echec:", err2)
        else: state["fb_story"] = today; print("FB story publiee:", r2)

json.dump(state, open("last.json", "w"))
if errors:
    raise SystemExit("Echecs: " + " | ".join(errors))
print("OK - IG + FB a jour pour", today)
