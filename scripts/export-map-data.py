#!/usr/bin/env python3
"""gaokao.db -> demos/unis.json 供地图使用。

本科 1644 所:双一流出旗子(短名),普通本科出点阵。
cs/med/fin 筛选标签由第四轮学科评估真实计算。
"""
import json, os, re, sqlite3

D = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect(os.path.join(D, "gaokao-data", "gaokao.db"))

SHORT = {"清华大学":"清华","北京大学":"北大","中国人民大学":"人大","北京航空航天大学":"北航",
"北京理工大学":"北理工","北京师范大学":"北师大","中国农业大学":"农大","中央民族大学":"央民",
"北京邮电大学":"北邮","中央财经大学":"央财","对外经济贸易大学":"贸大","南开大学":"南开",
"天津大学":"天大","哈尔滨工业大学":"哈工大","吉林大学":"吉大","东北大学":"东北大",
"大连理工大学":"大工","复旦大学":"复旦","上海交通大学":"上交","同济大学":"同济",
"华东师范大学":"华东师大","上海财经大学":"上财","南京大学":"南大","东南大学":"东南",
"浙江大学":"浙大","中国科学技术大学":"中科大","厦门大学":"厦大","山东大学":"山大",
"中国海洋大学":"海大","武汉大学":"武大","华中科技大学":"华科","湖南大学":"湖大",
"中南大学":"中南","国防科技大学":"国防科大","中山大学":"中大","华南理工大学":"华工",
"四川大学":"川大","电子科技大学":"电子科大","重庆大学":"重大","西安交通大学":"西交",
"西北工业大学":"西工大","西安电子科技大学":"西电","兰州大学":"兰大","西北农林科技大学":"西农",
"郑州大学":"郑大","云南大学":"云大","新疆大学":"新大","内蒙古大学":"内大",
"广西大学":"广西大","贵州大学":"贵大","海南大学":"琼大","西藏大学":"藏大",
"青海大学":"青大","宁夏大学":"宁大"}

def short(name):
    if name in SHORT: return SHORT[name]
    s = re.sub(r"(职业技术大学|职业技术学院|职业学院|高等专科学校|专科学校|大学|学院)$", "", name)
    return s[:6] if s else name[:4]

GRADE_ORD = {g: i for i, g in enumerate(
    ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-"])}
A_SET = {"A+", "A", "A-"}
CS_CODES = {"0812", "0835", "0839"}            # 计算机/软件/网安
MED_CODES = {"1002", "1003"}                   # 临床/口腔
FIN_CODES = {"0202", "0201", "0301"}           # 应用/理论经济学、法学

evals = {}
for uid, code, disc, grade in con.execute(
        "SELECT uni_id,code,discipline,grade FROM subject_eval"):
    evals.setdefault(uid, []).append((code, disc, grade))

out = []
q = """SELECT id,name,province,city,type,is_985,is_211,is_dfc,rank,
       baoyan_rate,master_pts,doctor_pts,intro,lng,lat,geo_src
       FROM universities WHERE level='本科' AND lng IS NOT NULL"""
for (uid, name, prov, city, tp, i985, i211, idfc, rank,
     by, mp, dp, intro, lng, lat, gsrc) in con.execute(q):
    ev = sorted(evals.get(uid, []), key=lambda e: GRADE_ORD.get(e[2], 9))
    tier = "985" if i985 else "211" if i211 else "dfc" if idfc else "ben"
    u = {"n": name, "s": short(name), "p": prov, "c": city or "",
         "ll": [round(lng, 5), round(lat, 5)], "t": tier, "tp": tp or ""}
    if rank: u["rank"] = rank
    if by: u["by"] = by
    if mp: u["mp"] = mp
    if dp: u["dp"] = dp
    if intro: u["intro"] = re.sub(r"\s+", "", str(intro))[:90]
    if ev:
        u["disc"] = [[d, g] for _, d, g in ev[:4]]
        u["m"] = " · ".join(d for _, d, g in ev[:3])
    codes = {c for c, _, g in ev if g in A_SET and c}
    if codes & CS_CODES: u["cs"] = 1
    if codes & MED_CODES: u["med"] = 1
    if codes & FIN_CODES: u["fin"] = 1
    if gsrc == "city-mean": u["approx"] = 1
    out.append(u)

out.sort(key=lambda u: ({"985": 0, "211": 1, "dfc": 2, "ben": 3}[u["t"]],
                        u.get("rank") or 9999))
path = os.path.join(D, "unis.json")
json.dump(out, open(path, "w"), ensure_ascii=False, separators=(",", ":"))
kb = os.path.getsize(path) // 1024
tiers = {}
for u in out: tiers[u["t"]] = tiers.get(u["t"], 0) + 1
print(f"导出 {len(out)} 所本科 -> unis.json ({kb} KB)")
print("分层:", tiers)
print("cs 强校:", sum("cs" in u for u in out),
      "/ med:", sum("med" in u for u in out),
      "/ fin:", sum("fin" in u for u in out))
print("样例:", json.dumps(next(u for u in out if u["n"] == "浙江大学"),
      ensure_ascii=False)[:300])
