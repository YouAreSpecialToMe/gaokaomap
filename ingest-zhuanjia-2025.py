#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""省「大数据专家版」xlsx 的 2025 专业录取 → admission_lines:用更全的专家版替换偏薄的 v2.xlsx 源。

泛化自 ingest-ah-2025.py(安徽首用)——`--province` 改省名即复用到 江西/广西/湘鄂粤/黑/新/琼 等缺口省。

专家版 xlsx:标题行 + "XXXX年招生计划"行 + 列名行 + 数据行(自动探测含「院校名称」+「最低位次」的表头行)。
每行=一个专业,取其 2025 录取(最低分/最低位次/录取人数;部分省含平均/最高)。**首个**同名列=2025
(专家版后面跟 2024/2023 同名列)。位次直接用专家版的(平台已按官方一分一段换算,**入库前务必抽查一致**)。
科类 物理/历史→物理类/历史类(老高考理/文、综合省原样);批次保留(高职专科→切片专科单列)。

幂等 + 可回滚:DELETE 旧 v2.xlsx 该省2025(先 dump 到 <db>.<code>2025-v2-backup.json)→ 跳过四头部校官方
回填已占的(校,专业)保官方 → INSERT 专家版 source='<code>-zhuanjia-2025'。
回滚:DELETE FROM admission_lines WHERE source='<code>-zhuanjia-2025';再从 backup.json 重灌 v2。
用法:python3 ingest-zhuanjia-2025.py <xlsx> --province 江西 [--replace-src ...] [--db ...] [--commit]
"""
import openpyxl, sqlite3, argparse, json

OFFICIAL_SRC = ('hit-2025-official', 'hust-2025-official', 'ruc-2025-official',
                'ustc-2025-official', 'toudang-promote-2025')
CODE = {'安徽': 'ah', '江西': 'jx', '广西': 'gx', '湖南': 'hn', '湖北': 'hb',
        '广东': 'gd', '黑龙江': 'hlj', '新疆': 'xj', '海南': 'hi'}
COLS = ('uni_name', 'uni_code', 'province', 'year', 'batch', 'subject', 'granularity',
        'major_code', 'major', 'major_note', 'sel_req', 'min_score', 'min_rank',
        'avg_score', 'avg_rank', 'max_score', 'enroll_n', 'source', 'subject_std')


def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return None
def _i(v):
    try: return int(float(v))
    except (TypeError, ValueError): return None


def read_rows(path, province, new_src):
    rows = list(openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True))
    hi = next(i for i, row in enumerate(rows[:6])
              if row and any(str(v).strip() == '院校名称' for v in row if v)
              and any(str(v).strip() in ('最低位次', '最低位次1') for v in row if v))
    hdr = [str(v).strip() if v is not None else '' for v in rows[hi]]
    col = {}
    for i, name in enumerate(hdr):
        if name and name not in col: col[name] = i          # 首个同名列 = 2025 段
    def g(row, *names):                                      # 录取列两种命名:无后缀(安徽)/带 *1 后缀(浙鄂);取首个命中
        for name in names:
            i = col.get(name)
            if i is not None and i < len(row): return row[i]
        return None
    out = []
    for row in rows[hi + 1:]:
        uni = str(g(row, '院校名称') or '').strip()
        mr = _i(g(row, '最低位次1', '最低位次'))               # 无位次的引擎用不上,丢
        if not uni or mr is None: continue
        kl = str(g(row, '科类') or '').strip()
        out.append((uni, str(g(row, '院校代码') or '').strip(), province, 2025, str(g(row, '批次') or '').strip(),
                    (kl + '类') if kl in ('物理', '历史') else kl, 'major',
                    str(g(row, '专业代码') or '').strip(), str(g(row, '专业名称') or '').strip(),
                    (str(g(row, '专业备注') or '').strip() or None), (str(g(row, '选科要求') or '').strip() or None),
                    _f(g(row, '最低分1', '最低分')), mr, _f(g(row, '平均分1', '平均分')),
                    _i(g(row, '平均位次1', '平均位次')), _f(g(row, '最高分1', '最高分')),
                    _i(g(row, '录取人数1', '录取人数')), new_src, kl))
    seen, ded = set(), []                                    # 去全同重复行(军校提前批等同校同专业同分多行)
    for r in out:
        k = (r[0], r[8], r[5], r[4], r[11], r[12], r[9])     # uni,major,subject,batch,min_score,min_rank,note
        if k in seen: continue
        seen.add(k); ded.append(r)
    return ded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('xlsx'); ap.add_argument('--province', required=True)
    ap.add_argument('--replace-src', default=None)
    ap.add_argument('--db', default='gaokao-data/gaokao.db')
    ap.add_argument('--commit', action='store_true')
    a = ap.parse_args()
    prov = a.province
    code = CODE.get(prov, prov)
    new_src = f'{code}-zhuanjia-2025'
    replace_src = a.replace_src or f'22-25年全国高校在{prov}的专业录取分数-v2.xlsx'
    rows = read_rows(a.xlsx, prov, new_src)
    c = sqlite3.connect(a.db)
    official = set((u, m) for u, m in c.execute(
        f"SELECT uni_name,major FROM admission_lines WHERE province=? AND year=2025 "
        f"AND granularity='major' AND source IN ({','.join('?' * len(OFFICIAL_SRC))})", (prov,) + OFFICIAL_SRC))
    keep = [r for r in rows if (r[0], r[8]) not in official]
    skipped = len(rows) - len(keep)
    before = c.execute("SELECT count(*) FROM admission_lines WHERE province=? AND year=2025 "
                       "AND granularity='major' AND min_rank IS NOT NULL", (prov,)).fetchone()[0]
    v2n = c.execute("SELECT count(*) FROM admission_lines WHERE province=? AND year=2025 "
                    "AND granularity='major' AND source=?", (prov, replace_src)).fetchone()[0]
    print(f"{prov} 专家版读到(有位次): {len(rows):,}  跳过官方回填重复: {skipped}  待插: {len(keep):,}")
    print(f"待删旧 v2「{replace_src}」: {v2n:,}")
    print(f"{prov}2025 可用专业行: {before:,}  →  预计 {before - v2n + len(keep):,}   新 source={new_src}")
    if not a.commit:
        print("=== DRY-RUN(未写库)。加 --commit ==="); return
    bak = a.db + f'.{code}2025-v2-backup.json'
    cols = [d[1] for d in c.execute("PRAGMA table_info(admission_lines)")]
    dump = [dict(zip(cols, row)) for row in c.execute(
        "SELECT * FROM admission_lines WHERE province=? AND year=2025 AND granularity='major' AND source=?", (prov, replace_src))]
    json.dump(dump, open(bak, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f"已备份 {len(dump):,} 条旧 v2 行 → {bak}")
    c.execute("BEGIN")
    c.execute("DELETE FROM admission_lines WHERE province=? AND year=2025 AND granularity='major' AND source IN (?,?)", (prov, replace_src, new_src))  # 同删 new_src → 幂等,防并发/重跑叠加重复
    c.executemany(f"INSERT INTO admission_lines ({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})", keep)
    c.commit()
    after = c.execute("SELECT count(*) FROM admission_lines WHERE province=? AND year=2025 "
                      "AND granularity='major' AND min_rank IS NOT NULL", (prov,)).fetchone()[0]
    print(f"✅ {prov}2025 可用专业行 {before:,} → {after:,}(+{after - before:,})")


if __name__ == '__main__':
    main()
