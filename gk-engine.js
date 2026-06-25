/* 冲稳保引擎 · 客户端版(node + 浏览器通用)。跑在 export-slices.py 导出的列存切片上,
   逻辑与服务端 recommend.py 对齐:score→位次 → 近3年加权 ρ(=专业位次/你的位次) → 冲稳保档
   → 院校层次+贴合度排序 → 每档12、每校2。无切片时前端回退服务端 API。 */
(function (global) {
  var SUBJ_EQ = { "综合": ["综合"], "物理": ["物理", "理科"], "历史": ["历史", "文科"], "理科": ["理科", "物理"], "文科": ["文科", "历史"] };
  var BANDS = { "冲": [0.85, 1.05, 0.95], "稳": [1.05, 1.25, 1.15], "保": [1.25, 1.80, 1.45] };
  var TOP_RANK_FLOOR = 20, TOP_FRAC = 0.0001; // 顶尖位次阈值=本省该科约前 0.01%(至少前 20),按考生规模自适应(小省~20、大省~70)
  var TOK = { "物理": "物", "化学": "化", "生物": "生", "历史": "史", "地理": "地", "政治": "政", "技术": "技" };
  function normToks(t) { t = String(t); for (var k in TOK) t = t.split(k).join(TOK[k]); return new Set(t.match(/[物化生史地政技]/g) || []); }
  function selOk(req, sel) {
    if (sel == null || req == null) return true;
    var r = String(req).trim(); if (!r || r.indexOf("不限") >= 0 || r === "-" || r === "无") return true;
    var toks = normToks(r); if (!toks.size) return true;
    if (/选\s*1|或/.test(r) || r.indexOf("/") >= 0) { for (var t of toks) if (sel.has(t)) return true; return false; }
    for (var t2 of toks) if (!sel.has(t2)) return false; return true;
  }
  function bandOf(rho, top) { // 顶尖位次(top):取消冲下限/保上限 —— 够得着的最热门不再出局,很稳的好学校纳入保
    if (rho < BANDS["冲"][0]) return top ? "冲" : null;
    if (rho < BANDS["冲"][1]) return "冲";
    if (rho < BANDS["稳"][1]) return "稳";
    if (rho < BANDS["保"][1]) return "保";
    return top ? "保" : null;
  }
  var strip = function (s) { return String(s).replace(/[(（][^)）]*[)）]/g, "").trim(); };
  function rankTbl(slice, subj, year) {
    var cands = SUBJ_EQ[subj] || [subj];
    for (var i = 0; i < cands.length; i++) { var r = slice.rank[cands[i]] && slice.rank[cands[i]][year]; if (r && r.pts && r.pts.length) return r; }
    return null;
  }
  function recommend(slice, uinfo, opt) {
    uinfo = uinfo || {}; opt = opt || {};
    var SU = slice.uinfo || {};                                 // 切片自带的完整 prestige(含冷门校)优先,unis.json 的 UINFO 兜底 → 与服务端 get_uinfo 对齐
    var subj = opt.subj || slice.subj, sel = opt.sel || null, cands = SUBJ_EQ[subj] || [subj], year = slice.years[0];
    var rt = rankTbl(slice, subj, year); if (!rt) return { error: "no_rank" };
    var pts = rt.pts, total = 0; for (var i = 0; i < pts.length; i++) if (pts[i][1] > total) total = pts[i][1];
    var floor = pts[pts.length - 1][1], topMin = pts[pts.length - 1][0], effR;   // 顶部封顶段(海南综合等省官方把高分并成一段,如「前105名」)→ 段内退回用分数细分位次,免冲稳保把好学校全压成「冲」误判
    if (floor > 10) { for (var ff = pts.length - 1; ff >= 0 && pts[ff][1] === floor; ff--) topMin = pts[ff][0]; effR = function (rk, sx) { return rk === floor && sx != null ? Math.max(1, floor - Math.round(sx - topMin)) : rk; }; } else effR = function (rk) { return rk; };
    var myRank;
    if (opt.rank) { myRank = opt.rank | 0; if (myRank < 1 || myRank > total * 1.1) return { error: "rank_oob" }; }
    else {
      var sc = opt.score, lo = 0, hi = pts.length; while (lo < hi) { var m = (lo + hi) >> 1; if (pts[m][0] <= sc) lo = m + 1; else hi = m; }
      if (lo - 1 < 0) return { error: "below_floor" }; myRank = pts[lo - 1][1];
    }
    if (opt.score != null) myRank = effR(myRank, opt.score);   // 封顶段:用分数把你的位次细分(否则前105名全=105、彼此分不出)
    var blRank = null;                                          // 本科线位次(切片 bl,按 SUBJ_EQ 解析,与 rankTbl 同口径)→ 没上线放开专科,与服务端 below_line 同源
    if (slice.bl) { var blc = SUBJ_EQ[subj] || [subj]; for (var bli = 0; bli < blc.length; bli++) if (slice.bl[blc[bli]] != null) { blRank = slice.bl[blc[bli]]; break; } }
    var belowLine = blRank != null && myRank > blRank;          // 位次比本科线位次更靠后 = 没上本科线
    var cohort = {}, eq = {}; cohort[year] = total; eq[year] = myRank;
    [year - 1, year - 2].forEach(function (yr) { var t = rankTbl(slice, subj, yr); if (t) { var c = 0; for (var j = 0; j < t.pts.length; j++) if (t.pts[j][1] > c) c = t.pts[j][1]; cohort[yr] = c; eq[yr] = Math.max(1, Math.round(myRank * c / total)); } });
    var pf = function (un) { var p = slice.plan[un] || slice.plan[strip(un)]; if (!p || !p[year] || !p[year - 1]) return 1; return Math.pow(Math.max(0.7, Math.min(1.4, p[year] / p[year - 1])), 0.2); };
    var subjOk = new Set(); slice.subjs.forEach(function (s, i) { if (cands.indexOf(s) >= 0) subjOk.add(i); });
    var mcWant = null;                                          // 测评×分数:只在 profile 命中的招生专业类内推荐(与服务端 engine mclasses 同源 uni_majors)
    if (opt.mclasses && opt.mclasses.length && slice.mcls && slice.mmc) {
      var mcIx = {}; slice.mcls.forEach(function (mc, i) { mcIx[mc] = i; });
      var ws = new Set(); opt.mclasses.forEach(function (mc) { if (mc in mcIx) ws.add(mcIx[mc]); });
      if (ws.size) mcWant = function (mi) { var arr = slice.mmc[mi]; if (!arr) return false; for (var z = 0; z < arr.length; z++) if (ws.has(arr[z])) return true; return false; };
    }
    var regionOk = null;   // 地区筛选:只推所选省份的学校(uinfo.p = 学校所在省)
    if (opt.regions && opt.regions.length) { var wantP = {}; for (var rp = 0; rp < opt.regions.length; rp++) wantP[opt.regions[rp]] = 1; regionOk = function (uIdx) { var f = SU[slice.unis[uIdx]] || uinfo[slice.unis[uIdx]]; return !!(f && f.p && wantP[f.p]); }; }
    var topStudent = myRank <= Math.max(TOP_RANK_FLOOR, Math.round(total * TOP_FRAC));   // 顶尖位次(本省该科前~0.01%,至少前20):放宽候选窗+bandOf(top)分档+同层次按最热门优先
    var A = slice.adm, n = A.r.length, cmap = {};
    [year, year - 1, year - 2].forEach(function (yr) {          // 必须按 year→y-2 降序(与服务端 dict 插入序一致),否则 cmap 键序不同 → 平局 tie-break 不同 → 个别项错位
      if (!(yr in eq)) return;
      var y2 = yr % 100, a = topStudent ? 1 : Math.floor(eq[yr] * 0.6), b = topStudent ? Math.max(Math.floor(eq[yr] * 2.4), 5000) : Math.floor(eq[yr] * 2.4);   // floor 对齐服务端 int(eq*0.6/2.4),否则边界位次的候选在/不在不一致 → 按组分档分叉
      for (var i = 0; i < n; i++) {
        if (A.y[i] !== y2 || !subjOk.has(A.j[i])) continue;
        if ((slice.majs[A.m[i]] || "").indexOf("预科") >= 0) continue;   // 预科永远排除(985/211 预科徽章泄漏)
        if (!belowLine && A.bt && A.bt[i]) continue;                     // 专科/高职仅在上了本科线时排除——低于线者反而需要专科
        var rr = A.r[i]; if (rr == null || rr < a || rr > b) continue;
        if (!selOk(slice.sels[A.sl[i]], sel)) continue;
        if (mcWant && !mcWant(A.m[i])) continue;
        if (regionOk && !regionOk(A.u[i])) continue;
        var k = A.u[i] + "|" + A.m[i];
        (cmap[k] = cmap[k] || []).push([yr, (yr === year ? effR(rr, A.sc[i] / 10) : rr) / eq[yr], i]);
      }
    });
    var items = [];
    // 大类多招生组同名(如 浙大「工科试验班」9 组,位次 202–7296)→ 按「组」分档而非合并:
    // 以最新年各组为锚,各组用「位次最近」的往年组平滑出 3 年加权 ρ、各自定档;每个(校,专业)
    // 取最贴合所在档中心的在档组。单组专业退化为原 3 年加权(逐项一致,无回归)。
    for (var k in cmap) {
      var recs = cmap[k], byY = {};
      for (var ri = 0; ri < recs.length; ri++) { var yy = recs[ri][0]; (byY[yy] = byY[yy] || []).push(recs[ri]); }
      var anchorY = -1; for (var ay in byY) { if (+ay > anchorY) anchorY = +ay; }
      if (anchorY < 0) continue;
      var un = slice.unis[A.u[byY[anchorY][0][2]]], pfu = pf(un), best = null;
      for (var gi = 0; gi < byY[anchorY].length; gi++) {
        var g = byY[anchorY][gi], gr = A.r[g[2]], ser = [[anchorY, g[1]]];
        [anchorY - 1, anchorY - 2].forEach(function (py) {
          var arr = byY[py]; if (!arr) return; var bn = null, bdist = Infinity;
          for (var ni = 0; ni < arr.length; ni++) { var nr = A.r[arr[ni][2]], d = Math.abs(nr - gr); if (d < bdist || (d === bdist && bn && nr < A.r[bn[2]])) { bdist = d; bn = arr[ni]; } }
          if (bn) ser.push([py, bn[1]]);
        });
        var ws = 0, rs = 0;
        for (var si = 0; si < ser.length; si++) { var wt = ser[si][0] === year ? 3 : ser[si][0] === year - 1 ? 2 : 1; ws += wt; rs += ser[si][1] * wt; }
        var grho = rs / ws * pfu, gb = bandOf(grho, topStudent); if (!gb) continue;
        var gd = Math.abs(grho - BANDS[gb][2]);
        if (!best || gd < best.d || (gd === best.d && gr < best.r)) best = { rho: grho, idx: g[2], yr: anchorY, d: gd, r: gr };
      }
      if (best) items.push([best.rho, un, slice.majs[A.m[best.idx]], best.idx, best.yr]);
    }
    var pres = function (un) { var f = SU[un] || uinfo[un] || SU[strip(un)] || uinfo[strip(un)]; return f ? [f.t === "985" ? 0 : f.t === "211" ? 1 : f.t === "dfc" ? 2 : 3, f.rank || 99999] : [3, 99999]; };
    items.sort(function (x, y) {
      var a = pres(x[1]), b = pres(y[1]); if (a[0] !== b[0]) return a[0] - b[0]; if (a[1] !== b[1]) return a[1] - b[1];
      if (!topStudent) { var dx = Math.abs(x[0] - BANDS[bandOf(x[0]) || "稳"][2]), dy = Math.abs(y[0] - BANDS[bandOf(y[0]) || "稳"][2]); if (dx !== dy) return dx - dy; }   // 顶尖位次跳过贴合度,直接 min_rank(最热门)优先
      var rx = effR(A.r[x[3]], A.sc[x[3]] / 10), ry = effR(A.r[y[3]], A.sc[y[3]] / 10); if (rx !== ry) return rx - ry;     // 确定性兜底序(与服务端一致):min_rank(封顶段用分数细分)→校名→专业,免平局依赖扫描/切片序
      if (x[1] !== y[1]) return x[1] < y[1] ? -1 : 1;
      return x[2] < y[2] ? -1 : x[2] > y[2] ? 1 : 0;
    });
    var ui = function (un) { return SU[un] || uinfo[un] || SU[strip(un)] || uinfo[strip(un)]; };
    var mk = function (ix, rho, fr) { var f = ui(slice.unis[A.u[ix]]); return { uni: slice.unis[A.u[ix]], major: slice.majs[A.m[ix]], minScore: A.sc[ix] / 10, minRank: A.r[ix], rho: Math.round(rho * 1000) / 1000, year: fr, note: fr === year ? "" : "据" + fr, selReq: slice.sels[A.sl[ix]] || "", enroll: A.e[ix] || null, ll: f && f.ll && f.ll[0] ? f.ll : null, tier: f ? f.t : null, city: f ? f.c : null }; };
    var out = { "冲": [], "稳": [], "保": [] }, pu = {};
    for (var t = 0; t < items.length; t++) {
      var it = items[t], rho = it[0], un = it[1], ix = it[3], bd = bandOf(rho, topStudent);
      if (!bd || (pu[un] || 0) >= 2 || out[bd].length >= 12) continue;
      pu[un] = (pu[un] || 0) + 1;
      out[bd].push(mk(ix, rho, it[4]));
    }
    var top_fb = false;                                         // 完全无匹配(数据缺失等):取该省该科最难进的专业作「冲」兜底
    if (!out["冲"].length && !out["稳"].length && !out["保"].length) {
      var eqv = eq[year] || 1, fb = [];
      for (var i2 = 0; i2 < n; i2++) { if (A.y[i2] !== year % 100 || !subjOk.has(A.j[i2]) || A.r[i2] == null) continue; if ((slice.majs[A.m[i2]] || "").indexOf("预科") >= 0) continue; if (!belowLine && A.bt && A.bt[i2]) continue; if (!selOk(slice.sels[A.sl[i2]], sel)) continue; if (mcWant && !mcWant(A.m[i2])) continue; fb.push(i2); }
      fb.sort(function (a, b) { return A.r[a] - A.r[b]; });
      var fbu = {};
      for (var g = 0; g < fb.length && out["冲"].length < 12; g++) {
        var un2 = slice.unis[A.u[fb[g]]]; if ((fbu[un2] || 0) >= 2) continue; fbu[un2] = (fbu[un2] || 0) + 1;
        out["冲"].push(mk(fb[g], A.r[fb[g]] / eqv, year));
      }
      top_fb = out["冲"].length > 0;
    }
    var notes = [], tot = out["冲"].length + out["稳"].length + out["保"].length;
    if (top_fb) notes.push("你的位次极高,常规冲稳保暂无匹配——下列为该省该科目最难进的顶尖专业(均作「冲」供参考)");
    else if (topStudent) notes.push("你的位次很高,已优先呈现「最好的学校 + 最热门专业」(冲=够一够的顶尖专业,保=很稳的好学校)");
    else if (tot < 12) notes.push("该省该分段专业级数据较薄,建议同时参考院校投档线");
    return { rank: myRank, eq: eq, bands: out, notes: notes };
  }
  var GK = {
    build: function (slice, uinfo) { return { slice: slice, recommend: function (opt) { return recommend(slice, uinfo, opt); } }; },
    recommend: recommend, bandOf: bandOf, selOk: selOk
  };
  if (typeof module !== "undefined" && module.exports) module.exports = GK; else global.GKEngine = GK;
})(typeof globalThis !== "undefined" ? globalThis : this);
