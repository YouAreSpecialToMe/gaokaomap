#!/usr/bin/env python3
"""通用省份 ETL v2:并行解析 + 串行写库。

相对 v1 的提速:
- python-calamine(Rust)替代 openpyxl,整文件只读一遍
- 表头探测在内存中扫前 3 行,不再重读文件
- 列式抽取替代 iterrows
- ProcessPoolExecutor 并行解析,主进程独占 SQLite
用法同 v1:python3 etl-batch2.py <省份> <根目录>
"""
import os, re, sqlite3, sys, time
from bisect import bisect_right
from concurrent.futures import ProcessPoolExecutor

PROV, ROOT = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "gaokao-data", "gaokao.db")

AL = {"uni": ["院校名称", "学校名称", "学校名字+备注", "学校", "院校"],
      "ucode": ["院校代码", "院校代号", "招生代码"],
      "major": ["专业名称", "专业全称", "专业"], "mcode": ["专业代码", "专业代号"],
      "note": ["专业备注", "备注"], "grp": ["所属专业组", "专业组", "专业组名称", "专业组+备注"],
      "sel": ["选科要求", "选科", "24年选科要求", "25年选科要求", "再选科目"],
      "subj": ["科类", "科类名称", "首选科目", "文理科", "科目"],
      "batch": ["批次", "批次名称", "录取批次"], "year": ["年份"],
      "min": ["最低分数", "最低分数线", "专业录取最低分", "录取最低分", "最低分",
              "最低分1", "投档最低分", "投档线"],
      "minrk": ["最低位次", "最低分位次", "专业录取最低位次", "录取最低位次",
                "最低位次1", "最低分排名", "最低分名次", "名次"],
      "avg": ["平均分"], "max": ["最高分"],
      "enroll": ["录取人数", "录取人数1", "投档人数"],
      "plan": ["招生人数", "计划人数", "招生计划(人)", "计划数", "计划"],
      "years": ["学制(年)", "学制"], "tuition": ["学费(元)", "学费", "学费（元）"]}
ALL_ALIASES = {a for v in AL.values() for a in v}

ART_RE = re.compile(r"艺术|美术|音乐|舞蹈|表演|表\(导\)演|表导演|播音|书法|编导|戏剧|影视")
def subj_std(s):
    if s is None: return None
    t = str(s).strip()
    if not t or t.lower() in ("none", "nan", "-"): return None
    if ART_RE.search(t): return "艺术"
    if "体育" in t: return "体育"
    if re.search(r"蒙授|蒙语|藏文|民语|民族班", t): return "民族语言"
    if "物理" in t: return "物理"
    if "历史" in t: return "历史"
    if re.match(r"^理(科|工)?$", t) or t == "理科综合": return "理科"
    if re.match(r"^文(科|史)?$", t) or t == "文科综合": return "文科"
    if re.search(r"综合|普通类|不限|本科$", t): return "综合"
    return "其他"

RANK_STD = ["年份", "科类", "分数(分)", "本段人数(人)", "累计人数(人)"]

def num(x):
    if x is None: return None
    if isinstance(x, (int, float)): return float(x)
    t = str(x).strip().replace(",", "")
    try: return float(t)
    except ValueError: return None
def I(x):
    v = num(x); return None if v is None else int(v)
def SS(x):
    if x is None: return None
    t = str(x).strip()
    return t if t and t.lower() not in ("none", "nan", "-") else None

def fname_year(p):
    m = re.findall(r"(20[12]\d)", os.path.basename(p))
    return int(m[-1]) if m else None

def parse_file(path):
    """子进程:读一遍 -> (kind, payload)。payload: {year:[rowtuple..]} 或 rank rows。"""
    try:
        from python_calamine import CalamineWorkbook
        wb = CalamineWorkbook.from_path(path)
        sheets = wb.sheet_names
        rows = []
        for sh in sheets:  # 多 sheet 文件(如按年份分表)整体串接,行内年份会区分
            rs = wb.get_sheet_by_name(sh).to_python(skip_empty_area=True)
            if rows and rs and rs[:1] == rows[:1]:
                rs = rs[1:]  # 各 sheet 同表头时去掉重复表头行
            rows.extend(rs)
    except Exception as e:
        return ("err", os.path.basename(path)[:40], str(e)[:60])
    if not rows: return ("skip", None, None)
    # 一分一段标准表优先判定(其表头会误中通用别名)
    for h in range(min(3, len(rows))):
        hdr = [SS(c) for c in rows[h]]
        if all(k in hdr for k in RANK_STD):
            idx = {k: hdr.index(k) for k in RANK_STD}
            out = []
            for r in rows[h+1:]:
                if len(r) <= max(idx.values()): continue
                sc = SS(r[idx["分数(分)"]])
                if not sc: continue
                m = re.match(r"(\d+)\s*[-~—]\s*(\d+)", sc)
                if m: lo, hi = sorted((int(m.group(1)), int(m.group(2))))
                elif sc.replace(".", "").isdigit(): lo = hi = int(float(sc))
                else: continue
                cum = I(r[idx["累计人数(人)"]])
                if cum is None: continue
                out.append((I(r[idx["年份"]]), SS(r[idx["科类"]]) or "综合",
                            cum, hi, lo, I(r[idx["本段人数(人)"]])))
            return ("rank", os.path.basename(path)[:48], out)
    # 表头探测:前 3 行里别名命中最多的一行
    best_h, best_hits = None, 0
    for h in range(min(3, len(rows))):
        hits = sum(1 for c in rows[h] if SS(c) in ALL_ALIASES)
        if hits > best_hits: best_h, best_hits = h, hits
    if best_h is None or best_hits < 2:
        return ("skip", None, None)
    hdr = [SS(c) for c in rows[best_h]]
    col = {}
    for k, cands in AL.items():
        for c in cands:
            if c in hdr: col[k] = hdr.index(c); break
    if "uni" not in col: return ("skip", None, None)
    kind = "major" if ("min" in col and "major" in col) else \
           "school" if "min" in col else \
           "plan" if "plan" in col else "skip"
    if kind == "skip": return ("skip", None, None)
    g = lambda r, k: (SS(r[col[k]]) if k in col and col[k] < len(r) else None)
    n = lambda r, k: (num(r[col[k]]) if k in col and col[k] < len(r) else None)
    i_ = lambda r, k: (I(r[col[k]]) if k in col and col[k] < len(r) else None)
    fy = fname_year(path)
    by_year, src = {}, os.path.basename(path)[:48]
    for r in rows[best_h+1:]:
        un = g(r, "uni")
        if not un: continue
        yr = i_(r, "year") or fy
        if not yr or yr < 2010 or yr > 2026: continue
        if kind == "plan":
            row = (un, g(r, "ucode"), PROV, yr, g(r, "subj"), g(r, "batch"), None,
                   g(r, "major"), g(r, "mcode"), g(r, "grp"), g(r, "note"),
                   g(r, "sel"), i_(r, "plan"), g(r, "years"), n(r, "tuition"), src)
        else:
            row = (un, g(r, "ucode"), PROV, yr, g(r, "batch"), g(r, "subj"), kind,
                   g(r, "mcode"), g(r, "major"), g(r, "note"), g(r, "sel"),
                   n(r, "min"), i_(r, "minrk"), n(r, "avg"), None, n(r, "max"),
                   i_(r, "enroll"), None, src)
        by_year.setdefault(yr, []).append(row)
    return (kind, src, by_year)

def main():
    t0 = time.time()
    SKIP = re.compile(r"college_data|征求志愿|说明|readme", re.I)
    files = [os.path.join(r, f) for r, _, fs in os.walk(ROOT) for f in fs
             if f.endswith(".xlsx") and not f.startswith("~$")
             and not SKIP.search(os.path.join(r, f))]
    print(f"{PROV}: {len(files)} 个文件,并行解析中…")
    results = []
    with ProcessPoolExecutor(max_workers=min(6, os.cpu_count() or 4)) as ex:
        for res in ex.map(parse_file, files):
            results.append(res)
    t1 = time.time()
    print(f"解析完成 {t1-t0:.1f}s")

    con = sqlite3.connect(DB, timeout=120)
    names = {nm: i for i, nm in con.execute("SELECT id,name FROM universities")}
    strip_paren = lambda s: re.sub(r"[(（][^)）]*[)）]", "", str(s)).strip()
    uid = lambda nm: names.get(nm) or names.get(strip_paren(nm)) if nm else None

    # rank_tables
    for kind, src, payload in results:
        if kind != "rank": continue
        years = {}
        for yr, subj, cum, hi, lo, seg in payload:
            if yr: years.setdefault(yr, []).append((subj, cum, hi, lo, seg))
        for yr, rs in years.items():
            have, = con.execute("SELECT COUNT(*) FROM rank_tables WHERE province=? AND year=?",
                                (PROV, yr)).fetchone()
            if have and yr != 2025: continue
            con.execute("DELETE FROM rank_tables WHERE province=? AND year=?", (PROV, yr))
            con.executemany("""INSERT INTO rank_tables
              (province,year,subject,level,rank_from,cum_rank,score_max,score_min,count_same)
              VALUES(?,?,?,NULL,NULL,?,?,?,?)""",
              [(PROV, yr, s, c, h, l, g) for s, c, h, l, g in rs])
            print(f"  rank {yr}: {len(rs)} 段 <- {src}")

    lookup = {}
    for yr, subj, smin, cum in con.execute(
            "SELECT year,subject,score_min,cum_rank FROM rank_tables WHERE province=? "
            "ORDER BY year,subject,score_min", (PROV,)):
        lookup.setdefault((yr, str(subj).strip()), []).append((smin, cum))
    ALIAS = {"物理类": ["物理类", "物理", "理科"], "历史类": ["历史类", "历史", "文科"],
             "物理": ["物理类", "物理", "理科"], "历史": ["历史类", "历史", "文科"],
             "理科": ["理科", "物理类"], "文科": ["文科", "历史类"],
             "综合": ["综合", "综合改革", "本科"], "综合改革": ["综合", "综合改革"]}
    def derive(yr, subj, score):
        if score is None: return None
        s = (subj or "综合").strip()
        if any(k in s for k in ("艺术", "体育", "音乐", "美术", "蒙授", "藏文", "民语")):
            return None
        for cand in ALIAS.get(s, [s]) + ["综合"]:
            tbl = lookup.get((yr, cand))
            if tbl:
                ss = [t[0] for t in tbl]
                i = bisect_right(ss, score) - 1
                return tbl[i][1] if i >= 0 else None
        return None

    cands = {"major": {}, "school": {}, "plan": {}}
    for kind, src, payload in results:
        if kind in ("rank", "skip"): continue
        if kind == "err":
            print(f"  ✗ {src}: {payload}"); continue
        for yr, rows in payload.items():
            q = sum(1 for r in rows if r[12 if kind != "plan" else 12] is not None)
            cands[kind].setdefault(yr, []).append((q, rows, src))

    if not cands["major"] and not cands["school"]:
        print(f"⚠️ {PROV}: 零提取,保护性退出"); con.close(); sys.exit(2)
    con.execute("DELETE FROM admission_lines WHERE province=?", (PROV,))
    con.execute("DELETE FROM enrollment_plans WHERE province=?", (PROV,))
    ADM = """INSERT INTO admission_lines
      (uni_id,uni_name,uni_code,province,year,batch,subject,granularity,major_code,
       major,major_note,sel_req,min_score,min_rank,avg_score,avg_rank,max_score,
       enroll_n,line_diff,source,subject_std)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    tot = {"major": 0, "school": 0, "plan": 0}
    for kind in ("major", "school"):
        for yr in sorted(cands[kind]):
            q, rows, src = max(cands[kind][yr], key=lambda t: (t[0], len(t[1])))
            out, dv = [], 0
            for r in rows:
                rk = r[12]
                if rk is None and r[11] is not None:
                    d = derive(yr, r[5], r[11])
                    if d is not None: rk = d; dv += 1
                out.append((uid(r[0]),) + r[:12] + (rk,) + r[13:] + (subj_std(r[5]),))
            con.executemany(ADM, out); tot[kind] += len(out)
            print(f"  {kind} {yr}: {len(out):,}(位次 {sum(1 for o in out if o[13]):,},反推 {dv}) <- {src}")
    for yr in sorted(cands["plan"]):
        if yr < 2022: continue
        q, rows, src = max(cands["plan"][yr], key=lambda t: (t[0], len(t[1])))
        con.executemany(f"""INSERT INTO enrollment_plans
          (uni_id,uni_name,uni_code,province,year,subject,batch,enroll_type,major,
           major_code,major_group,major_note,sel_req,plan_n,years,tuition,source)
          VALUES({','.join('?'*17)})""", [(uid(r[0]),) + r for r in rows])
        tot["plan"] += len(rows)
        print(f"  plan {yr}: {len(rows):,} <- {src}")
    con.commit(); con.close()
    print(f"{PROV}: major {tot['major']:,} / school {tot['school']:,} / plan {tot['plan']:,}")
    print(f"总耗时 {time.time()-t0:.1f}s(解析 {t1-t0:.1f}s + 写库 {time.time()-t1:.1f}s)")

if __name__ == "__main__":
    main()
