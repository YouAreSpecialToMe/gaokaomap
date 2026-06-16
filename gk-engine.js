/* 冲稳保引擎 · 客户端版(node + 浏览器通用)。跑在 export-slices.py 导出的列存切片上,
   逻辑与服务端 recommend.py 对齐:score→位次 → 近3年加权 ρ(=专业位次/你的位次) → 冲稳保档
   → 院校层次+贴合度排序 → 每档12、每校2。无切片时前端回退服务端 API。 */
(function (global) {
  var SUBJ_EQ = { "综合": ["综合"], "物理": ["物理", "理科"], "历史": ["历史", "文科"], "理科": ["理科", "物理"], "文科": ["文科", "历史"] };
  var BANDS = { "冲": [0.85, 1.05, 0.95], "稳": [1.05, 1.25, 1.15], "保": [1.25, 1.80, 1.45] };
  var TOK = { "物理": "物", "化学": "化", "生物": "生", "历史": "史", "地理": "地", "政治": "政", "技术": "技" };
  function normToks(t) { t = String(t); for (var k in TOK) t = t.split(k).join(TOK[k]); return new Set(t.match(/[物化生史地政技]/g) || []); }
  function selOk(req, sel) {
    if (sel == null || req == null) return true;
    var r = String(req).trim(); if (!r || r.indexOf("不限") >= 0 || r === "-" || r === "无") return true;
    var toks = normToks(r); if (!toks.size) return true;
    if (/选\s*1|或/.test(r) || r.indexOf("/") >= 0) { for (var t of toks) if (sel.has(t)) return true; return false; }
    for (var t2 of toks) if (!sel.has(t2)) return false; return true;
  }
  function bandOf(rho) { for (var b in BANDS) { var v = BANDS[b]; if (v[0] <= rho && rho < v[1]) return b; } return null; }
  var strip = function (s) { return String(s).replace(/[(（][^)）]*[)）]/g, "").trim(); };
  function rankTbl(slice, subj, year) {
    var cands = SUBJ_EQ[subj] || [subj];
    for (var i = 0; i < cands.length; i++) { var r = slice.rank[cands[i]] && slice.rank[cands[i]][year]; if (r && r.pts && r.pts.length) return r; }
    return null;
  }
  function recommend(slice, uinfo, opt) {
    uinfo = uinfo || {}; opt = opt || {};
    var subj = opt.subj || slice.subj, sel = opt.sel || null, cands = SUBJ_EQ[subj] || [subj], year = slice.years[0];
    var rt = rankTbl(slice, subj, year); if (!rt) return { error: "no_rank" };
    var pts = rt.pts, total = 0; for (var i = 0; i < pts.length; i++) if (pts[i][1] > total) total = pts[i][1];
    var myRank;
    if (opt.rank) { myRank = opt.rank | 0; if (myRank < 1 || myRank > total * 1.1) return { error: "rank_oob" }; }
    else {
      var sc = opt.score, lo = 0, hi = pts.length; while (lo < hi) { var m = (lo + hi) >> 1; if (pts[m][0] <= sc) lo = m + 1; else hi = m; }
      if (lo - 1 < 0) return { error: "below_floor" }; myRank = pts[lo - 1][1];
    }
    var cohort = {}, eq = {}; cohort[year] = total; eq[year] = myRank;
    [year - 1, year - 2].forEach(function (yr) { var t = rankTbl(slice, subj, yr); if (t) { var c = 0; for (var j = 0; j < t.pts.length; j++) if (t.pts[j][1] > c) c = t.pts[j][1]; cohort[yr] = c; eq[yr] = Math.max(1, Math.round(myRank * c / total)); } });
    var pf = function (un) { var p = slice.plan[un] || slice.plan[strip(un)]; if (!p || !p[year] || !p[year - 1]) return 1; return Math.pow(Math.max(0.7, Math.min(1.4, p[year] / p[year - 1])), 0.2); };
    var subjOk = new Set(); slice.subjs.forEach(function (s, i) { if (cands.indexOf(s) >= 0) subjOk.add(i); });
    var A = slice.adm, n = A.r.length, cmap = {};
    Object.keys(eq).map(Number).forEach(function (yr) {
      var y2 = yr % 100, a = eq[yr] * 0.6, b = eq[yr] * 2.4;
      for (var i = 0; i < n; i++) {
        if (A.y[i] !== y2 || !subjOk.has(A.j[i])) continue;
        var rr = A.r[i]; if (rr == null || rr < a || rr > b) continue;
        if (!selOk(slice.sels[A.sl[i]], sel)) continue;
        var k = A.u[i] + "|" + A.m[i];
        (cmap[k] = cmap[k] || []).push([yr, rr / eq[yr], i]);
      }
    });
    var items = [];
    for (var k in cmap) {
      var recs = cmap[k].sort(function (x, y) { return y[0] - x[0]; });
      var w = recs.map(function (r) { return r[0] === year ? 3 : r[0] === year - 1 ? 2 : 1; });
      var sw = w.reduce(function (p, q) { return p + q; }, 0), rho = recs.reduce(function (s, r, i) { return s + r[1] * w[i]; }, 0) / sw;
      var idx = recs[0][2], un = slice.unis[A.u[idx]];
      rho *= pf(un);
      items.push([rho, un, slice.majs[A.m[idx]], idx, recs[0][0]]);
    }
    var pres = function (un) { var f = uinfo[un] || uinfo[strip(un)]; return f ? [f.t === "985" ? 0 : f.t === "211" ? 1 : f.t === "dfc" ? 2 : 3, f.rank || 99999] : [3, 99999]; };
    items.sort(function (x, y) {
      var a = pres(x[1]), b = pres(y[1]); if (a[0] !== b[0]) return a[0] - b[0]; if (a[1] !== b[1]) return a[1] - b[1];
      return Math.abs(x[0] - BANDS[bandOf(x[0]) || "稳"][2]) - Math.abs(y[0] - BANDS[bandOf(y[0]) || "稳"][2]);
    });
    var ui = function (un) { return uinfo[un] || uinfo[strip(un)]; };
    var mk = function (ix, rho, fr) { var f = ui(slice.unis[A.u[ix]]); return { uni: slice.unis[A.u[ix]], major: slice.majs[A.m[ix]], minScore: A.sc[ix] / 10, minRank: A.r[ix], rho: Math.round(rho * 1000) / 1000, year: fr, note: fr === year ? "" : "据" + fr, selReq: slice.sels[A.sl[ix]] || "", enroll: A.e[ix] || null, ll: f && f.ll && f.ll[0] ? f.ll : null, tier: f ? f.t : null, city: f ? f.c : null }; };
    var out = { "冲": [], "稳": [], "保": [] }, pu = {};
    for (var t = 0; t < items.length; t++) {
      var it = items[t], rho = it[0], un = it[1], ix = it[3], bd = bandOf(rho);
      if (!bd || (pu[un] || 0) >= 2 || out[bd].length >= 12) continue;
      pu[un] = (pu[un] || 0) + 1;
      out[bd].push(mk(ix, rho, it[4]));
    }
    var top_fb = false;                                          // 位次极高:常规三档全空 → 取该省该科最难进的顶尖专业作「冲」(对齐服务端兜底)
    if (!out["冲"].length && !out["稳"].length && !out["保"].length) {
      var eqv = eq[year] || 1, fb = [];
      for (var i2 = 0; i2 < n; i2++) { if (A.y[i2] !== year % 100 || !subjOk.has(A.j[i2]) || A.r[i2] == null) continue; if (!selOk(slice.sels[A.sl[i2]], sel)) continue; fb.push(i2); }
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
    else if (tot < 12) notes.push("该省该分段专业级数据较薄,建议同时参考院校投档线");
    return { rank: myRank, eq: eq, bands: out, notes: notes };
  }
  var GK = {
    build: function (slice, uinfo) { return { slice: slice, recommend: function (opt) { return recommend(slice, uinfo, opt); } }; },
    recommend: recommend, bandOf: bandOf, selOk: selOk
  };
  if (typeof module !== "undefined" && module.exports) module.exports = GK; else global.GKEngine = GK;
})(typeof globalThis !== "undefined" ? globalThis : this);
