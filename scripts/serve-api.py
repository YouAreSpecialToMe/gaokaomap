#!/usr/bin/env python3
"""高考地图只读 API。用法: python3 serve-api.py [端口=8787]

GET /api/meta                         省份×科类×可用年份
GET /api/recommend?prov=&subj=&score=&year=&sel=物,化
GET /api/uni?name=浙江大学&prov=浙江   院校画像+学科评估+本省近三年线
"""
import json, os, re, sqlite3, sys, urllib.parse
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recommend import engine, DB, ALIAS, SUBJ_EQ
import quiz_data as QZ
from bisect import bisect_right

def rank_of(prov, subj_std, score, year=2025):
    con = db()
    for cand in ALIAS.get(subj_std, [subj_std]):
        t = con.execute("""SELECT score_min,cum_rank FROM rank_tables
            WHERE province=? AND year=? AND subject=? ORDER BY score_min""",
            (prov, year, cand)).fetchall()
        if t:
            ss=[r[0] for r in t]
            i=bisect_right(ss, score)-1
            con.close()
            return t[i][1] if i>=0 else None
    con.close(); return None

@lru_cache(maxsize=512)
def quiz_unis(mclass, prov, subj, score):
    r = rank_of(prov, subj, score)
    if not r: return []
    con = db()
    rows = con.execute("""SELECT uni_name,major,min_score,min_rank,year
        FROM admission_lines
        WHERE province=? AND year>=2024 AND granularity='major' AND subject_std IN (?,?)
          AND min_rank BETWEEN ? AND ?
          AND major IN (SELECT major FROM uni_majors WHERE mclass=?)
        ORDER BY year DESC, ABS(min_rank-?)""",
        (prov, *(SUBJ_EQ.get(subj,(subj,))+(subj,))[:2],
         int(r*0.75), int(r*1.8), mclass, int(r*1.15))).fetchall()
    seen, out = set(), []
    uinfo = {x[0]:(x[1],x[2],x[3],x[4],x[5]) for x in con.execute(
        "SELECT name,lng,lat,is_985,is_211,is_dfc FROM universities")}
    for row in rows:
        if row["uni_name"] in seen: continue
        seen.add(row["uni_name"])
        inf = uinfo.get(row["uni_name"])
        out.append({"uni": row["uni_name"], "major": row["major"],
                    "minScore": row["min_score"], "minRank": row["min_rank"],
                    "year": row["year"],
                    "ll": [inf[0], inf[1]] if inf and inf[0] else None,
                    "tier": ("985" if inf and inf[2] else "211" if inf and inf[3]
                             else "dfc" if inf and inf[4] else "ben") if inf else None})
        if len(out) >= 6: break
    con.close()
    return out

def db():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    return con

@lru_cache(maxsize=1)
def meta():
    con = db()
    provs = {}
    for r in con.execute("""SELECT province,subject,MAX(year) y FROM rank_tables
                            GROUP BY province,subject"""):
        std = next((k for k, v in ALIAS.items() if r["subject"] in v), None)
        if std:
            p = provs.setdefault(r["province"], {"subjects": set(), "rankYear": 0})
            p["subjects"].add(std)
            p["rankYear"] = max(p["rankYear"], r["y"])
    out = [{"province": p, "subjects": sorted(v["subjects"]),
            "rankYear": v["rankYear"]} for p, v in sorted(provs.items())]
    con.close()
    return {"provinces": out, "dataYears": "2017-2025",
            "disclaimer": "数据来自各省考试院等公开信息整理,仅供参考,不构成志愿填报依据"}

@lru_cache(maxsize=2048)
def uni_card(name, prov):
    con = db()
    strip = re.sub(r"[(（][^)）]*[)）]", "", name).strip()
    u = con.execute("SELECT * FROM universities WHERE name IN (?,?)",
                    (name, strip)).fetchone()
    if not u: con.close(); return {"error": "未找到该院校"}
    ev = [{"discipline": r["discipline"], "grade": r["grade"]} for r in con.execute(
        """SELECT discipline,grade FROM subject_eval WHERE uni_id=?
           ORDER BY CASE grade WHEN 'A+' THEN 0 WHEN 'A' THEN 1 WHEN 'A-' THEN 2
           WHEN 'B+' THEN 3 ELSE 4 END LIMIT 6""", (u["id"],))]
    lines = []
    if prov:
        lines = [dict(r) for r in con.execute(
            """SELECT year,subject_std subj,granularity,major,min_score,min_rank
               FROM admission_lines WHERE uni_name IN (?,?) AND province=?
                 AND year>=2023 AND min_rank IS NOT NULL
               ORDER BY year DESC, min_rank LIMIT 40""", (name, strip, prov))]
    out = {"name": u["name"], "province": u["province"], "city": u["city"],
           "tier": "985" if u["is_985"] else "211" if u["is_211"]
                   else "双一流" if u["is_dfc"] else (u["level"] or ""),
           "type": u["type"], "rank": u["rank"], "baoyan": u["baoyan_rate"],
           "masterPts": u["master_pts"], "doctorPts": u["doctor_pts"],
           "intro": (u["intro"] or "")[:120], "ll": [u["lng"], u["lat"]],
           "eval": ev, "lines": lines}
    con.close()
    return out

class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a): pass

    def do_GET(self):
        try:
            u = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            if u.path == "/api/meta":
                return self._send(meta())
            if u.path == "/api/recommend":
                prov, subj = q.get("prov"), q.get("subj")
                if not prov or not subj or not q.get("score", "").isdigit():
                    return self._send({"error": "参数:prov/subj/score 必填"}, 400)
                sel = set(q["sel"].split(",")) if q.get("sel") else None
                r = engine(prov, subj, int(q["score"]),
                           int(q.get("year", 2025)), sel)
                return self._send(r, 200 if "error" not in r else 422)
            if u.path == "/api/quiz":
                return self._send({"questions": QZ.QUESTIONS, "scale": QZ.SCALE,
                                   "dims": QZ.DIM_NAMES})
            if u.path == "/api/quiz/match":
                try:
                    vals = [int(x) for x in q.get("scores", "").split(",")]
                    assert len(vals) == 6
                except Exception:
                    return self._send({"error": "scores=R,I,A,S,E,C 六个整数"}, 400)
                us = dict(zip(QZ.DIMS, vals))
                mx = max(us.values()) or 1
                profile = {QZ.DIM_NAMES[d]: round(us[d] * 100 / 12) for d in QZ.DIMS}
                top = []
                prov, subj, sc = q.get("prov"), q.get("subj"), q.get("score")
                for mc, code, fit in QZ.match_classes(us, top=6):
                    item = {"mclass": mc, "code": code, "fit": fit,
                            "majors": QZ.SAMPLE_MAJORS.get(mc, "")}
                    if prov and subj and sc and sc.isdigit():
                        item["unis"] = quiz_unis(mc, prov, subj, int(sc))
                    top.append(item)
                return self._send({"profile": profile, "top": top})
            if u.path == "/api/uni":
                if not q.get("name"):
                    return self._send({"error": "参数:name 必填"}, 400)
                return self._send(uni_card(q["name"], q.get("prov", "")))
            return self._send({"error": "not found"}, 404)
        except Exception as e:
            return self._send({"error": f"internal: {type(e).__name__} {e}"}, 500)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f"gaokao API on http://127.0.0.1:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
