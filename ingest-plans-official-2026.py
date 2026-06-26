import sys,re,sqlite3,argparse,pandas as pd
ALIAS={
 'uni_name':['院校名称','学校','学校名称'],'uni_code':['院校代码','学校代码'],
 'major':['专业名称','专业'],'major_code':['专业代码'],
 'major_group':['专业组','专业组名称','专业组代码','院校专业组'],
 'major_note':['专业备注','专业简注','备注','简注说明','其他说明'],'subject':['科类','首选科目'],
 'batch':['批次','批次名称'],'sel_req':['选科','选科要求','科目要求','次选科目'],
 'plan_n':['计划数','计划人数','2026年计划','招生人数'],
 'years':['学制'],'tuition':['学费','学费(元/年)','收费标准'],'enroll_type':['计划性质','计划类别'],
}
ART=['美术','音乐','舞蹈','体育','播音','书法','戏剧','戏曲','服装','表演','艺术','艺考']
PROV={'北京','天津','上海','重庆','河北','山西','内蒙古','辽宁','吉林','黑龙江','江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南','广东','广西','海南','四川','贵州','云南','西藏','陕西','甘肃','青海','宁夏','新疆','香港','澳门','台湾'}
PROG_KW=['预科','民族','中外合作','合作办学','中德','中英','中法','中美','中澳','中俄','专项','定向','对口','联合培养','较高收费','特殊计划','面向','民办','独立','公办']
STRIP_PROV=False
def strip_loc(n):
    n=re.sub(r'[\[【](公办|民办|中外合作办学|合作办学|其[它他]|境[内外])[^\]】]*[\]】]','',str(n)).strip()
    parts=re.split(r'(?=[（(])',n); keep=parts[0]           # 按"("拆段:基础名 + 各括号段
    for seg in parts[1:]:                                  # 遇到含"项目类型"关键词的括号段就截断、丢弃其后
        if any(k in seg for k in PROG_KW): break           # (民族大学等关键词在基础名/无前置括号→保留)
        keep+=seg                                          # 校区/分校/(北京)/(华东)等不含关键词→保留
    n=keep.strip()
    if STRIP_PROV:                                         # 仅天津式(每校都加(省))才删尾部省份括号
        m=re.search(r'[（(]([^（）()]+)[）)]\s*$',n)
        if m and m.group(1) in PROV: n=n[:m.start()].strip()
    return n
def derive_subj(sk,bn,default):
    bn=str(bn or '')
    if any(k in bn for k in ['艺术','艺考','体育']): return None
    if sk is not None and not(isinstance(sk,float) and pd.isna(sk)):
        s=str(sk)
        if any(k in s for k in ART): return None
        if '综合' in s or '不分' in s: return '综合'
        if '物理' in s or '理科' in s: return '物理'
        if '历史' in s or '文科' in s: return '历史'
        return default or None
    return default
def load(path):
    raw=pd.read_excel(path,header=None,dtype=str)
    hi=next((i for i in range(min(6,len(raw))) if any(any(a in str(v) for a in ALIAS['uni_name']) for v in raw.iloc[i].tolist())),0)
    df=pd.read_excel(path,header=hi,dtype=str); df.columns=[str(c).strip() for c in df.columns]
    out=pd.DataFrame()
    for f,al in ALIAS.items():
        col=next((c for c in df.columns if c in al),None)
        out[f]=df[col] if col else None
    return out
ap=argparse.ArgumentParser()
ap.add_argument('--province',required=True); ap.add_argument('--year',type=int,default=2026)
ap.add_argument('--db',required=True); ap.add_argument('--source',default='guanfang-2026-plan')
ap.add_argument('--default-subject',default=None); ap.add_argument('--strip-province',action='store_true'); ap.add_argument('--dry',action='store_true'); ap.add_argument('files',nargs='+')
a=ap.parse_args()
STRIP_PROV=a.strip_province
df=pd.concat([load(f) for f in a.files],ignore_index=True); n0=len(df)
df['subject']=df.apply(lambda r:derive_subj(r['subject'],r['batch'],a.default_subject),axis=1)
df=df[df['subject'].notna()].copy()
df['uni_name']=df['uni_name'].map(strip_loc)
df['plan_n']=pd.to_numeric(df['plan_n'],errors='coerce'); df=df[df['plan_n'].notna()]
df['tuition']=pd.to_numeric(df['tuition'],errors='coerce')
print(f"读入{n0} → 普通类{len(df)}(滤{n0-len(df)}) | subject={df['subject'].value_counts().to_dict()}")
print(f"batch={df['batch'].value_counts().to_dict()}")
print(f"计划合计={int(df['plan_n'].sum())} 院校={df['uni_name'].nunique()}")
if a.dry: sys.exit()
con=sqlite3.connect(a.db); cur=con.cursor()
cur.execute("DELETE FROM enrollment_plans WHERE province=? AND year=?",(a.province,a.year))
cols=['uni_name','uni_code','province','year','subject','batch','enroll_type','major','major_code','major_group','major_note','sel_req','plan_n','years','tuition','source']
rows=[(r['uni_name'],r['uni_code'],a.province,a.year,r['subject'],r['batch'],r['enroll_type'],r['major'],r['major_code'],r['major_group'],r['major_note'],r['sel_req'],int(r['plan_n']),r['years'],(None if pd.isna(r['tuition']) else float(r['tuition'])),a.source) for _,r in df.iterrows()]
cur.executemany(f"INSERT INTO enrollment_plans ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",rows)
con.commit(); con.close(); print(f"✅ 入库 {len(rows)} 行 → {a.province} {a.year}")
