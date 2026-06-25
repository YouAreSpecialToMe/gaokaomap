#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安徽 2025 专业级录取 → admission_lines:用「安徽专家版」更全源替换偏薄的 v2.xlsx 源。

安徽专家版 xlsx(院校专业组):标题行1、分组表头行2、列名行3、数据行4+。每行=一个专业,
取其 2025 录取(最低分/位次/平均/录取人数)。位次已离线校验与安徽 2025 官方一分一段 100% 自洽
(71% 同分带内、其余 ≤2000、0 例 >1万)。批次保留(高职(专科)批 → 切片 bt=1 专科单列)。

幂等 + 可回滚:
  - DELETE 旧 v2.xlsx 安徽 2025(先 dump 到 <db>.ah2025-v2-backup.json 供回滚)
  - 跳过四头部校官方回填已占的 (校,专业)(华科/中科大/哈工大/人大/清北复交浙交兜底),保官方
  - INSERT 专家版 → source='ah-zhuanjia-2025'
回滚:DELETE FROM admission_lines WHERE source='ah-zhuanjia-2025';再从 backup.json 重灌 v2。
用法:python3 ingest-ah-2025.py <xlsx> [--db ...] [--commit]
"""
import openpyxl, sqlite3, argparse, os, json

OFFICIAL_SRC = ('hit-2025-official', 'hust-2025-official', 'ruc-2025-official',
                'ustc-2025-official', 'toudang-promote-2025')
REPLACE_SRC = '22-25年全国高校在安徽的专业录取分数-v2.xlsx'
NEW_SRC = 'ah-zhuanjia-2025'
COLS = ('uni_name', 'uni_code', 'province', 'year', 'batch', 'subject', 'granularity',
        'major_code', 'major', 'major_note', 'sel_req', 'min_score', 'min_rank',
        'avg_score', 'avg_rank', 'max_score', 'enroll_n', 'source', 'subject_std')


def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return None
def _i(v):
    try: return int(float(v))
    except (TypeError, ValueError): return None


def read_rows(path):
    # 按列名读(clean 提取版单表头;专家版有 3 行表头且 2024/2023 同名列在后 → 取首个=2025)
    rows = list(openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True))
    hi = next(i for i, row in enumerate(rows[:6])
              if row and any(str(v).strip() == '院校名称' for v in row if v)
              and any(str(v).strip() == '最低位次' for v in row if v))
    hdr = [str(v).strip() if v is not None else '' for v in rows[hi]]
    col = {}
    for i, name in enumerate(hdr):
        if name and name not in col: col[name] = i       # 首个同名列(专家版 → 2025 段)
    def g(row, name):
        i = col.get(name); return row[i] if i is not None and i < len(row) else None
    out = []
    for row in rows[hi + 1:]:
        uni = str(g(row, '院校名称') or '').strip()
        mr = _i(g(row, '最低位次'))                       # 无位次的引擎用不上,丢
        if not uni or mr is None: continue
        kl = str(g(row, '科类') or '').strip()            # 物理/历史
        out.append((uni, str(g(row, '院校代码') or '').strip(), '安徽', 2025, str(g(row, '批次') or '').strip(),
                    (kl + '类') if kl in ('物理', '历史') else kl, 'major',
                    str(g(row, '专业代码') or '').strip(), str(g(row, '专业名称') or '').strip(),
                    (str(g(row, '专业备注') or '').strip() or None), (str(g(row, '选科要求') or '').strip() or None),
                    _f(g(row, '最低分')), mr, _f(g(row, '平均分')), _i(g(row, '平均位次')), _f(g(row, '最高分')),
                    _i(g(row, '录取人数')), NEW_SRC, kl))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('xlsx'); ap.add_argument('--db', default='gaokao-data/gaokao.db')
    ap.add_argument('--commit', action='store_true')
    a = ap.parse_args()
    rows = read_rows(a.xlsx)
    c = sqlite3.connect(a.db)
    official = set((u, m) for u, m in c.execute(
        f"SELECT uni_name,major FROM admission_lines WHERE province='安徽' AND year=2025 "
        f"AND granularity='major' AND source IN ({','.join('?' * len(OFFICIAL_SRC))})", OFFICIAL_SRC))
    keep = [r for r in rows if (r[0], r[8]) not in official]
    skipped = len(rows) - len(keep)
    before = c.execute("SELECT count(*) FROM admission_lines WHERE province='安徽' AND year=2025 "
                       "AND granularity='major' AND min_rank IS NOT NULL").fetchone()[0]
    v2n = c.execute("SELECT count(*) FROM admission_lines WHERE province='安徽' AND year=2025 "
                    "AND granularity='major' AND source=?", (REPLACE_SRC,)).fetchone()[0]
    print(f"专家版读到(有位次): {len(rows):,}  跳过官方回填重复: {skipped}  待插: {len(keep):,}")
    print(f"待删旧 v2.xlsx 安徽2025: {v2n:,}")
    print(f"安徽2025 可用专业行: {before:,}  →  预计 {before - v2n + len(keep):,}")
    if not a.commit:
        print("=== DRY-RUN(未写库)。加 --commit ==="); return
    # backup v2 rows for rollback
    bak = a.db + '.ah2025-v2-backup.json'
    cols = [d[1] for d in c.execute("PRAGMA table_info(admission_lines)")]
    dump = [dict(zip(cols, row)) for row in c.execute(
        "SELECT * FROM admission_lines WHERE province='安徽' AND year=2025 AND granularity='major' AND source=?", (REPLACE_SRC,))]
    json.dump(dump, open(bak, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f"已备份 {len(dump):,} 条旧 v2 行 → {bak}")
    c.execute("BEGIN")
    c.execute("DELETE FROM admission_lines WHERE province='安徽' AND year=2025 AND granularity='major' AND source=?", (REPLACE_SRC,))
    c.executemany(f"INSERT INTO admission_lines ({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})", keep)
    c.commit()
    after = c.execute("SELECT count(*) FROM admission_lines WHERE province='安徽' AND year=2025 "
                      "AND granularity='major' AND min_rank IS NOT NULL").fetchone()[0]
    print(f"✅ 安徽2025 可用专业行 {before:,} → {after:,}(+{after - before:,})")


if __name__ == '__main__':
    main()
