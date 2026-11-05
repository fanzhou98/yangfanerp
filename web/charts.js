/*!
 * 洋帆 ERP 正式图表组件 v0.2 · 基于 prototype/charts/charts.js
 * 纯原生 JavaScript + SVG，无第三方依赖，可直接被 CSP(script-src 'self') 加载。
 * 只读渲染：不请求数据、不修改业务状态。数据由调用方传入。
 */
(function (global) {
  'use strict';

  function known(value) { return value !== null && value !== undefined && value !== '' && isFinite(Number(value)); }
  function formatter(opts) { return opts.type === 'cents' || !opts.type ? money : function (value) { return num(value, 3) + (opts.unit ? ' ' + opts.unit : ''); }; }
  function axisFormatter(opts) { return opts.type === 'cents' || !opts.type ? axisMoney : function (value) { return num(value, 3); }; }

  /* ---------------- 格式化 ---------------- */
  function money(cents) {
    var v = Number(cents || 0) / 100;
    return '¥ ' + v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function compactMoney(cents, withSymbol) {
    var v = Number(cents || 0), a = Math.abs(v) / 100, sign = v < 0 ? '-' : '';
    var unit = withSymbol === false ? '' : '¥';
    if (a >= 1e8) return sign + unit + trim((a / 1e8).toFixed(2)) + '亿';
    if (a >= 1e4) return sign + unit + trim((a / 1e4).toFixed(1)) + '万';
    if (a >= 1e3) return sign + unit + trim((a / 1e3).toFixed(1)) + '千';
    return sign + unit + Math.round(a).toLocaleString('zh-CN');
  }
  function axisMoney(cents) {
    var v = Number(cents || 0), a = Math.abs(v) / 100, sign = v < 0 ? '-' : '';
    if (a >= 1e8) return sign + trim((a / 1e8).toFixed(a >= 1e9 ? 0 : 1)) + '亿';
    if (a >= 1e4) return sign + trim((a / 1e4).toFixed(a >= 1e5 ? 0 : 1)) + '万';
    return sign + Math.round(a).toLocaleString('zh-CN');
  }
  function trim(s) { return String(s).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1'); }
  function num(v, digits) {
    var d = digits == null ? 2 : digits;
    return Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: d });
  }
  function pct(v, digits) {
    var d = digits == null ? 1 : digits;
    return trim(Number(v || 0).toFixed(d)) + '%';
  }
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* ---------------- 刻度 ---------------- */
  function niceNum(range, round) {
    if (!(range > 0)) return 1;
    var exp = Math.floor(Math.log10(range));
    var f = range / Math.pow(10, exp), nf;
    if (round) nf = f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10;
    else nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
    return nf * Math.pow(10, exp);
  }
  function niceScale(min, max, count) {
    count = count || 4;
    min = Number(min); max = Number(max);
    if (!isFinite(min) || !isFinite(max)) { min = 0; max = 1; }
    if (min > max) { var t = min; min = max; max = t; }
    if (min === max) { if (max === 0) max = 1; else { min = Math.min(0, min); max = Math.max(0,max); } }
    var step = niceNum((max - min) / Math.max(1, count - 1), true);
    var nmin = Math.floor(min / step) * step;
    var nmax = Math.ceil(max / step) * step;
    var ticks = [];
    for (var v = nmin; v <= nmax + step * 1e-9; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
    return { min: nmin, max: nmax, step: step, ticks: ticks };
  }

  /* ---------------- DOM 工具 ---------------- */
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function wrapChars(text, n) {
    var chars = Array.from(String(text || '')), out = [];
    for (var i = 0; i < chars.length; i += n) out.push(chars.slice(i, i + n).join(''));
    return out.length ? out : [''];
  }
  function tableHTML(spec) {
    var headers = spec.headers || [], rows = spec.rows || [];
    return '<details class="yc-table"><summary>查看数据表<span>' + rows.length + ' 行</span></summary>' +
      '<div class="yc-table-wrap"><table><thead><tr>' +
      headers.map(function (h) { return '<th>' + esc(h) + '</th>'; }).join('') +
      '</tr></thead><tbody>' +
      rows.map(function (r) {
        return '<tr>' + r.map(function (cell, i) {
          return '<td class="' + (i === 0 ? '' : 'num') + '">' + esc(cell) + '</td>';
        }).join('') + '</tr>';
      }).join('') +
      '</tbody></table></div></details>';
  }
  function finish(root, opts) {
    if (opts.caption) {
      var p = document.createElement('p');
      p.className = 'yc-caption';
      p.textContent = opts.caption;
      root.appendChild(p);
    }
    if (opts.table && opts.table.rows && opts.table.rows.length) {
      root.insertAdjacentHTML('beforeend', tableHTML(opts.table));
    }
  }
  function empty(root, opts) {
    var div = document.createElement('div');
    div.className = 'yc-empty';
    div.innerHTML = '<b>' + esc(opts.emptyTitle || '暂无数据') + '</b>' +
      (opts.emptyHint ? '<p>' + esc(opts.emptyHint) + '</p>' : '');
    root.appendChild(div);
  }
  function paint(root) {
    root.querySelectorAll('[data-yc-w]').forEach(function (el) { el.style.width = el.getAttribute('data-yc-w') + '%'; });
    root.querySelectorAll('[data-yc-left]').forEach(function (el) { el.style.left = el.getAttribute('data-yc-left') + '%'; });
    root.querySelectorAll('[data-yc-bg]').forEach(function (el) { el.style.background = el.getAttribute('data-yc-bg'); });
    root.querySelectorAll('[data-yc-track-w]').forEach(function (el) { el.style.width = el.getAttribute('data-yc-track-w') + '%'; el.style.minWidth = el.getAttribute('data-yc-track-min') || '0'; });
  }
  function tipNode() {
    var tip = document.createElement('div');
    tip.className = 'yc-tip';
    tip.setAttribute('role','status');tip.setAttribute('aria-live','polite');
    return tip;
  }
  function placeTip(tip, plot, px, py) {
    var w = plot.clientWidth || 1;
    var below = py < 62;
    tip.classList.toggle('below', below);
    tip.classList.add('show');
    var half = Math.max(70, (tip.offsetWidth || 140) / 2);
    var left = Math.max(half + 6, Math.min(w - half - 6, px));
    tip.style.left = left + 'px';
    tip.style.top = (below ? py + 6 : Math.max(2, py - 8)) + 'px';
  }

  /* ---------------- 挂载 / 重绘 ---------------- */
  function mount(root, type, opts) {
    if (!root) return;
    root.classList.add('yc-chart');
    root.__yc = { type: type, opts: opts || {} };
    if (!root.__ycRO) {
      var last = 0;
      root.__ycRO = new ResizeObserver(function () {
        if(window.matchMedia&&window.matchMedia('print').matches)return;
        var w = root.clientWidth;
        if (Math.abs(w - last) > 2) { last = w; render(root); }
      });
      root.__ycRO.observe(root);
    }
    render(root, true);
  }
  function render(root, force) {
    var st = root.__yc;
    if (!st) return;
    var w = Math.max(240, Math.round(root.clientWidth || 800));
    if (!force && root.__ycW === w) return;
    root.__ycW = w;
    clear(root);
    var opts = st.opts || {};
    if (st.type === 'line') drawLine(root, opts, w);
    else if (st.type === 'waterfall') drawWaterfall(root, opts, w);
    else if (st.type === 'rank') drawRank(root, opts, w);
    else if (st.type === 'bar') drawBar(root, opts, w);
    else if (st.type === 'composition') drawComposition(root, opts, w);
    else if (st.type === 'dot') drawDotRange(root, opts, w);
    paint(root);
  }

  /* ---------------- 折线图 ---------------- */
  function drawLine(root, opts, W) {
    var raw = opts.data || [];
    var format=formatter(opts),axisFormat=axisFormatter(opts);
    var data = raw.map(function (d) {
      var valid=known(d.value);
      return { date:d.date, value:valid?Number(d.value):null, pending:Number(d.pending)||0, known:valid, state:d.state||(valid?'已复核':'无单据') };
    });
    var valid = data.filter(function (d) { return d.known; });
    if (!data.length || !valid.length) {
      empty(root, {emptyTitle:opts.emptyTitle||'所选期间暂无已复核数据',emptyHint:opts.emptyHint||'无单据与待复核日期不当作0，不绘制假坐标轴。'});
      if(opts.caption){var caption=document.createElement('p');caption.className='yc-caption';caption.textContent=opts.caption;root.appendChild(caption);}
      return;
    }
    if (valid.length < 3 && opts.sparse !== false) {
      drawSparseLine(root, opts, data, valid, format);
      return;
    }

    var narrow = W < 540;
    var H = opts.height || (narrow ? 196 : 248);
    var P = { l: narrow ? 44 : 58, r: narrow ? 20 : 14, t: 14, b: narrow ? 27 : 32 };
    var plotW = W - P.l - P.r, plotH = H - P.t - P.b;
    var maxV = Math.max.apply(null, [0].concat(valid.map(function (d) { return d.value; })));
    var minV = Math.min.apply(null, [0].concat(valid.map(function (d) { return d.value; })));
    var scale = niceScale(minV, maxV, narrow ? 3 : 4);
    var n = data.length;
    var stepX = n > 1 ? plotW / (n - 1) : 0;
    var times=data.map(function(d){return Date.parse(d.date.length===7?d.date+'-01T00:00:00Z':d.date+'T00:00:00Z');});
    var temporal=times.every(isFinite)&&times[n-1]>times[0];
    var x = function (i) { return n>1 ? P.l+(temporal?(times[i]-times[0])/(times[n-1]-times[0])*plotW:i*stepX) : P.l+plotW/2; };
    var y = function (v) { return P.t + plotH - ((v-scale.min)/(scale.max-scale.min))*plotH; };

    var uid = 'ycg' + Math.random().toString(36).slice(2, 9);
    var grid = scale.ticks.map(function (t) {
      return '<line class="yc-grid" x1="' + P.l + '" x2="' + (P.l + plotW) + '" y1="' + y(t) + '" y2="' + y(t) + '"/>' +
        '<text class="yc-axis" x="' + (P.l - 8) + '" y="' + (y(t) + 4) + '" text-anchor="end">' + esc(axisFormat(t)) + '</text>';
    }).join('');

    var labelCount = Math.min(n, narrow ? 3 : 6);
    var labelSet = new Set();
    for (var k = 0; k < labelCount; k++) labelSet.add(Math.round(k * (n - 1) / Math.max(1, labelCount - 1)));
    var xLabels = Array.from(labelSet).map(function (i) {
      return '<text class="yc-axis" x="' + x(i) + '" y="' + (H - 8) + '" text-anchor="middle">' + esc(data[i].date.length===7?data[i].date:data[i].date.slice(5)) + '</text>';
    }).join('');

    var segments = [], seg = [];
    data.forEach(function (d, i) {
      if (d.known) seg.push(i);
      else if (seg.length) { segments.push(seg); seg = []; }
    });
    if (seg.length) segments.push(seg);

    var lines = segments.map(function (s) {
      return '<path fill="none" stroke="#356f68" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" d="' +
        s.map(function (i, j) { return (j ? 'L' : 'M') + x(i) + ' ' + y(data[i].value); }).join(' ') + '"/>';
    }).join('');

    var areas = segments.filter(function (s) { return s.length > 1; }).map(function (s) {
      var d = 'M' + x(s[0]) + ' ' + y(0) + ' ' + s.map(function (i) { return 'L' + x(i) + ' ' + y(data[i].value); }).join(' ') +
        ' L' + x(s[s.length - 1]) + ' ' + y(0) + ' Z';
      return '<path d="' + d + '" fill="url(#' + uid + ')" stroke="none"/>';
    }).join('');

    var points = data.map(function (d, i) {
      var full = esc(d.date) + '：' + (d.known ? '已复核销售 ' + esc(format(d.value)) : d.state) +
        (d.pending ? '，待复核 ' + d.pending + ' 笔' : '');
      return d.known
        ? '<circle class="yc-pt" cx="' + x(i) + '" cy="' + y(d.value) + '" r="3.4" fill="#356f68"><title>' + full + '</title></circle>'
        : '<circle class="yc-pt" cx="' + x(i) + '" cy="' + y(0) + '" r="3" fill="#fff" stroke="#356f68" stroke-width="1.4" opacity=".7"><title>' + full + '</title></circle>';
    }).join('');

    var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" tabindex="0" aria-label="' +
      esc(opts.aria || ('销售趋势，共 ' + n + ' 天，最高 ' + format(maxV) + '；使用左右方向键查看逐日数据')) + '">' +
      '<defs><linearGradient id="' + uid + '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="#356f68" stop-opacity=".16"/><stop offset="100%" stop-color="#356f68" stop-opacity="0"/>' +
      '</linearGradient></defs>' + grid + areas + lines + points +
      '<line x1="' + P.l + '" x2="' + (P.l + plotW) + '" y1="' + y(0) + '" y2="' + y(0) + '" stroke="#cfdad3"/>' +
      xLabels +
      '<g class="yc-hover" display="none"><line stroke="#8ba79a" stroke-dasharray="3 3" y1="' + P.t + '" y2="' + (P.t + plotH) + '"/>' +
      '<circle r="5" fill="#fff" stroke="#356f68" stroke-width="2"/></g>' +
      '<rect class="yc-hit" x="' + P.l + '" y="' + P.t + '" width="' + plotW + '" height="' + plotH + '" fill="transparent"/>' +
      '</svg>';

    var plot = document.createElement('div');
    plot.className = 'yc-plot';
    plot.innerHTML = svg;
    root.appendChild(plot);
    var tip = tipNode();
    plot.appendChild(tip);

    var $svg = plot.querySelector('svg');
    var $hover = plot.querySelector('.yc-hover');
    var $line = $hover.querySelector('line');
    var $dot = $hover.querySelector('circle');
    var $hit = plot.querySelector('.yc-hit');
    var active = -1;

    function show(i) {
      var d = data[i];
      if (!d) return;
      active = i;
      var px = x(i), py = d.known ? y(d.value) : y(0);
      $hover.removeAttribute('display');
      $line.setAttribute('x1', px); $line.setAttribute('x2', px);
      $dot.setAttribute('cx', px); $dot.setAttribute('cy', py);
      $dot.setAttribute('fill', d.known ? '#fff' : '#fff');
      $dot.setAttribute('stroke', d.known ? '#356f68' : '#8ba79a');
      tip.innerHTML = '<b>' + esc(d.date) + '</b>' +
        (d.known
          ? '<span>已复核销售 <strong>' + esc(format(d.value)) + '</strong></span>'
          : '<span>'+esc(d.state)+'</span>') +
        '<span>待复核 <strong>' + d.pending + '</strong> 笔</span>';
      var r = $svg.getBoundingClientRect();
      placeTip(tip, plot, px / W * r.width, py / H * r.height);
    }
    function hide() {
      tip.classList.remove('show');
      $hover.setAttribute('display', 'none');
      active = -1;
    }

    $hit.addEventListener('pointermove', function (e) {
      var r = $svg.getBoundingClientRect();
      var px = (e.clientX - r.left) * (W / r.width);
      var i=0;for(var at=1;at<n;at++)if(Math.abs(x(at)-px)<Math.abs(x(i)-px))i=at;
      show(Math.max(0, Math.min(n - 1, i)));
    });
    $hit.addEventListener('pointerleave', function(e){if(e.pointerType!=='touch')hide();});
    $hit.addEventListener('pointerdown',function(e){if(e.pointerType==='touch'){var r=$svg.getBoundingClientRect(),px=(e.clientX-r.left)*W/r.width,i=0;for(var at=1;at<n;at++)if(Math.abs(x(at)-px)<Math.abs(x(i)-px))i=at;show(i);}});
    $svg.addEventListener('focus', function () { show(active >= 0 ? active : n - 1); });
    $svg.addEventListener('blur', hide);
    $svg.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { hide(); return; }
      var i = active >= 0 ? active : n - 1, next = null;
      if (e.key === 'ArrowLeft') next = i - 1;
      else if (e.key === 'ArrowRight') next = i + 1;
      else if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = n - 1;
      if (next == null) return;
      e.preventDefault();
      show(Math.max(0, Math.min(n - 1, next)));
    });

    finish(root, opts);
  }

  /* 少于 3 个已复核日：不画空坐标轴，改为紧凑的数值条 */
  function drawSparseLine(root, opts, data, valid, format) {
    var total = valid.reduce(function (n, d) { return n + d.value; }, 0);
    var max = Math.max(1, Math.max.apply(null, valid.map(function (d) { return d.value; })));
    var rows = valid.map(function (d) {
      var w = Math.max(1, Math.min(100, d.value / max * 100));
      return '<div class="yc-sparse-row"><span class="yc-sparse-date">' + esc(d.date) + '</span>' +
        '<span class="yc-sparse-track"><i data-yc-w="' + w.toFixed(2) + '"></i></span>' +
        '<b>' + esc(format(d.value)) + '</b>' +
        '<small>' + (d.pending ? '待复核 ' + d.pending + ' 笔' : '无待复核') + '</small></div>';
    }).join('');
    var box = document.createElement('div');
    box.className = 'yc-sparse';
    box.innerHTML = '<div class="yc-sparse-head"><div><b>本期仅 ' + valid.length + ' 天有已复核数据</b>' +
      '<span>共 ' + data.length + ' 天；已复核合计 ' + esc(format(total)) + '</span></div>' +
      '<span class="yc-sparse-badge">样本不足，不画趋势</span></div>' +
      '<div class="yc-sparse-list">' + rows + '</div>';
    root.appendChild(box);
    if (opts.caption) {
      var caption = document.createElement('p'); caption.className = 'yc-caption'; caption.textContent = opts.caption; root.appendChild(caption);
    }
    if (opts.table && opts.table.rows && opts.table.rows.length) root.insertAdjacentHTML('beforeend', tableHTML(opts.table));
  }

  /* ---------------- 瀑布图 ---------------- */
  function drawWaterfall(root, opts, W) {
    var items = (opts.data || []).filter(function (d) { return known(d.value); });
    if (!items.length) {
      empty(root, { emptyTitle: opts.emptyTitle || '暂无可拆解的收入与成本', emptyHint: opts.emptyHint, caption: opts.caption });
      return;
    }
    var run=0;
    var bars=items.map(function(d){
      var value=Number(d.value),start=known(d.start)?Number(d.start):run,end=known(d.end)?Number(d.end):start+value;
      run=end;return {label:d.label,short:d.short,value:value,start:start,end:end,total:!!d.total,subtotal:!!d.subtotal};
    });
    if(!items.some(function(d){return d.total;}))bars.push({label:opts.totalLabel||'净利润',short:opts.totalShort||'净利润',value:run,start:0,end:run,total:true});
    var lo = Math.min.apply(null, [0].concat(bars.map(function (b) { return Math.min(b.start, b.end); })));
    var hi = Math.max.apply(null, [0].concat(bars.map(function (b) { return Math.max(b.start, b.end); })));
    if (hi === lo) {
      empty(root, { emptyTitle:'已确认金额均为0',emptyHint:'没有金额变化，完整零值见数据表。' });
      finish(root,opts);return;
    }

    var narrow = W < Math.max(720,bars.length*95);
    var H = opts.height || (narrow ? 250 : 300);
    var P = { l: narrow ? 46 : 58, r: 14, t: 22, b: narrow ? 46 : 40 };
    var plotW = W - P.l - P.r, plotH = H - P.t - P.b;
    var scale = niceScale(lo, hi, narrow ? 3 : 4);
    var y = function (v) { return P.t + plotH - (v - scale.min) / (scale.max - scale.min) * plotH; };

    var grid = scale.ticks.map(function (t) {
      return '<line class="yc-grid" x1="' + P.l + '" x2="' + (P.l + plotW) + '" y1="' + y(t) + '" y2="' + y(t) + '"/>' +
        '<text class="yc-axis" x="' + (P.l - 8) + '" y="' + (y(t) + 4) + '" text-anchor="end">' + esc(axisMoney(t)) + '</text>';
    }).join('');

    var slot = plotW / bars.length;
    var barW = Math.max(18, Math.min(narrow ? 28 : 88, slot * 0.56));
    var gap = (slot - barW) / 2;

    var svgBars = bars.map(function (b, i) {
      var left = P.l + i * slot + gap;
      var top = Math.min(y(b.start), y(b.end));
      var height = b.value===0?0:Math.abs(y(b.start)-y(b.end));
      var color = b.total ? (b.subtotal ? '#93b2cc' : '#628eb5') : b.value >= 0 ? '#356f68' : '#d9a34b';
      var valY = b.value >= 0 ? top - 8 : top + height + 14;
      var labelText = narrow && b.short ? b.short : b.label;
      var labelLines = wrapChars(labelText, Math.max(1,Math.min(6,Math.floor(slot/12))));
      var labelTspans = labelLines.map(function (line, j) {
        return '<tspan x="' + (left + barW / 2) + '" dy="' + (j ? 13 : 0) + '">' + esc(line) + '</tspan>';
      }).join('');
      var full = b.label + '：' + money(b.value) + (b.total ? '' : '，累计 ' + money(b.end));
      return '<g class="yc-wf-bar" tabindex="0" role="img" aria-label="' + esc(full) + '" data-i="' + i + '">' +
        '<rect x="' + left + '" y="' + top + '" width="' + barW + '" height="' + height + '" rx="3" fill="' + color + '"/>' +
        '<text class="yc-label" x="' + (left + barW / 2) + '" y="' + valY + '" text-anchor="middle">' + (b.value===0||narrow||height<22?'':esc(compactMoney(b.value, true))) + '</text>' +
        '<text class="yc-axis" x="' + (left + barW / 2) + '" y="' + (H - (labelLines.length > 1 ? 24 : 12)) + '" text-anchor="middle">' + labelTspans + '</text>' +
        '</g>';
    }).join('');

    var needsValues=narrow||bars.some(function(b){return b.value!==0&&Math.abs(y(b.start)-y(b.end))<22;});

    var connectors = bars.slice(0, -1).map(function (b, i) {
      var x1 = P.l + i * slot + gap + barW, x2 = P.l + (i + 1) * slot + gap;
      return '<line x1="' + x1 + '" x2="' + x2 + '" y1="' + y(b.end) + '" y2="' + y(b.end) + '" stroke="#9db1a8" stroke-dasharray="4 3"/>';
    }).join('');

    var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" tabindex="0" aria-label="' +
      esc(opts.aria || ('收入与成本瀑布图，最终净利润 ' + money(run))) + '">' +
      grid + '<line x1="' + P.l + '" x2="' + (P.l + plotW) + '" y1="' + y(0) + '" y2="' + y(0) + '" stroke="#b9c8bf"/>' +
      connectors + svgBars + '</svg>';

    var plot = document.createElement('div');
    plot.className = 'yc-plot';
    plot.innerHTML = svg;
    root.appendChild(plot);
    var tip = tipNode();
    plot.appendChild(tip);
    var $svg = plot.querySelector('svg');

    if(needsValues){
      var values=document.createElement('div');values.className='yc-waterfall-values';
      values.innerHTML='<p>小项金额见下表；柱长按原金额比例，不放大小项。</p>'+bars.map(function(b){return '<div class="yc-wf-value-row"><span>'+esc(b.label)+'</span><b>'+esc(money(b.value))+'</b><small>累计 '+esc(money(b.end))+'</small></div>';}).join('');
      root.appendChild(values);
    }

    function showBar(i, target) {
      var b = bars[i];
      if (!b) return;
      var left = P.l + i * slot + gap;
      tip.innerHTML = '<b>' + esc(b.label) + '</b><span>金额 <strong>' + esc(money(b.value)) + '</strong></span>' +
        (b.total ? '<span>结果 <strong>' + esc(money(b.end)) + '</strong></span>' : '<span>累计 <strong>' + esc(money(b.end)) + '</strong></span>');
      var r = $svg.getBoundingClientRect();
      var px = (left + barW / 2) / W * r.width;
      var py = Math.min(y(b.start), y(b.end)) / H * r.height;
      placeTip(tip, plot, px, py);
      target.classList.add('is-active');
    }
    function hideBar() { tip.classList.remove('show'); plot.querySelectorAll('.yc-wf-bar.is-active').forEach(function (n) { n.classList.remove('is-active'); }); }
    plot.querySelectorAll('.yc-wf-bar').forEach(function (g) {
      var i = Number(g.dataset.i);
      g.addEventListener('pointerenter', function () { showBar(i, g); });
      g.addEventListener('pointerleave', hideBar);
      g.addEventListener('focus', function () { showBar(i, g); });
      g.addEventListener('blur', hideBar);
    });

    finish(root, opts);
  }

  /* ---------------- 排名条 ---------------- */
  function drawRank(root, opts, W) {
    var rows = (opts.data || []).filter(function (d) { return known(d.value); });
    if (!rows.length) {
      empty(root, { emptyTitle: opts.emptyTitle || '暂无排名数据', emptyHint: opts.emptyHint, caption: opts.caption });
      return;
    }
    var sorted = rows.slice().sort(function (a, b) { return Number(b.value) - Number(a.value); });
    var format=formatter(opts),axisFormat=axisFormatter(opts),values=sorted.map(function(r){return Number(r.value);}),scale=niceScale(Math.min.apply(null,[0].concat(values)),Math.max.apply(null,[0].concat(values)),4);
    var extent=scale.max-scale.min,zero=(0-scale.min)/extent*100;
    var html='<div class="yc-rank">'+sorted.map(function(r,i){
      var value=Number(r.value),pos=(value-scale.min)/extent*100,width=Math.abs(pos-zero),selected=String(r.key)===String(opts.selected),tag=opts.onSelect?'button':'div';
      return '<'+tag+(tag==='button'?' type="button"':'')+' class="yc-rank-row'+(value===0?' is-zero':'')+(selected?' is-selected':'')+'" data-key="'+esc(r.key==null?i:r.key)+'"'+(opts.onSelect?' aria-pressed="'+selected+'"':'')+' aria-label="'+esc(r.label+'，'+format(value)+(known(r.share_pct)?'，占比 '+pct(r.share_pct):''))+'">'+
        '<span class="yc-rank-label"><span title="'+esc(r.label)+'">'+esc(r.label)+'</span>'+(r.sub?'<small>'+esc(r.sub)+'</small>':'')+'</span>'+
        '<span class="yc-rank-track"><i class="'+(value<0?'is-negative':'')+'" data-yc-left="'+Math.min(pos,zero)+'" data-yc-w="'+width+'"></i><b class="yc-rank-zero" data-yc-left="'+zero+'"></b></span>'+
        '<span class="yc-rank-value">'+(value?esc(format(value)):'0')+(known(r.share_pct)?'<small>'+esc(pct(r.share_pct))+'</small>':'')+'</span></'+tag+'>';
    }).join('')+'</div><div class="yc-rank-scale"><span>'+esc(axisFormat(scale.min))+'</span><span>'+esc(axisFormat(scale.max))+'</span></div>';
    var plot = document.createElement('div');
    plot.className = 'yc-plot';
    plot.innerHTML = html;
    root.appendChild(plot);
    if (opts.onSelect) {
      plot.querySelectorAll('.yc-rank-row').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var key = btn.dataset.key;
          var row = sorted.find(function (r, i) { return String(r.key == null ? i : r.key) === key; });
          opts.onSelect(row, key);
        });
      });
    }
    finish(root, opts);
  }

  /* ---------------- 100% 构成 ---------------- */
  function drawComposition(root, opts, W) {
    var rows = opts.data || [], parts = opts.parts || [];
    var total = rows.reduce(function (n, r) { return n + Number(r.total || 0); }, 0);
    var maxTotal = rows.reduce(function (n, r) { return Math.max(n, Number(r.total || 0)); }, 0);
    if (!rows.length || !total) {
      empty(root, { emptyTitle: opts.emptyTitle || '暂无库存构成', emptyHint: opts.emptyHint, caption: opts.caption });
      return;
    }
    var legend = '<div class="yc-legend">' + parts.map(function (p) {
      return '<span><i data-yc-bg="' + p.color + '"></i>' + esc(p.label) + '</span>';
    }).join('') + '</div>';

    var body = rows.map(function (r) {
      var t = Number(r.total) || 0;
      var segs = parts.map(function (p) {
        var v = Number((r.values || {})[p.key] || 0);
        if (!(v > 0)) return '';
        var share=r.percentages&&known(r.percentages[p.key])?Number(r.percentages[p.key]):t?v/t*100:0;
        return '<span class="' + (p.light ? 'is-light' : '') + '" data-yc-w="' + share.toFixed(2) + '" data-yc-bg="' + p.color + '" title="' +
          esc(p.label + '：' + num(v, 1) + ' ' + (opts.unit || '吨') + '，占 ' + pct(share)) + '">' +
          (share >= 12 ? esc(pct(share, 0)) : '') + '</span>';
      }).join('');
      var details = parts.map(function (p) {
        var v = Number((r.values || {})[p.key] || 0);
        if (!(v > 0)) return '';
        var share=r.percentages&&known(r.percentages[p.key])?Number(r.percentages[p.key]):t?v/t*100:0;
        return '<span><i data-yc-bg="' + p.color + '"></i>' + esc(p.label) + ' ' + esc(pct(share, 1)) + ' · ' +
          esc(num(v, 1) + ' ' + (opts.unit || '吨')) + '</span>';
      }).join('');
      var barWidth = maxTotal ? (t > 0 ? Math.max(0.5, t / maxTotal * 100) : 100) : 100;
      return '<div class="yc-comp-row"><div class="yc-comp-head"><strong>' + esc(r.label) + '</strong><small>' +
        esc(num(t, 1) + ' ' + (opts.unit || '吨')) + '</small></div>' +
        '<div class="yc-comp-track' + (t > 0 ? '' : ' is-zero') + '" data-yc-track-w="' + barWidth.toFixed(2) + '" data-yc-track-min="' + (t > 0 ? '2px' : '0') + '" role="img" aria-label="' + esc(r.label + '：' + parts.map(function (p) {
          return p.label + ' ' + num((r.values || {})[p.key] || 0, 1);
        }).join('，')) + '">' + (segs || '<span class="is-empty">无库存</span>') + '</div>' +
        (details ? '<div class="yc-comp-details">' + details + '</div>' : '') + '</div>';
    }).join('');

    var plot = document.createElement('div');
    plot.className = 'yc-plot';
    plot.innerHTML = legend + '<div class="yc-comp">' + body + '</div><div class="yc-comp-scale"><span>0</span><span>' + esc(num(maxTotal, 1) + ' ' + (opts.unit || '吨')) + '</span></div>';
    root.appendChild(plot);
    finish(root, opts);
  }

  /* ---------------- 上次 vs 当天 ---------------- */
  function drawDotRange(root, opts, W) {
    var rows=(opts.data||[]);var valid=rows.filter(function(r){return known(r.now)&&known(r.prev)&&Number(r.prev)>0;});
    if (!valid.length) {
      empty(root, { emptyTitle: opts.emptyTitle || '本期无同期可比出品率', emptyHint: opts.emptyHint, caption: opts.caption });
      return;
    }
    var max = niceScale(0, Math.max(1, Math.max.apply(null, valid.map(function (r) {
      return Math.max(Number(r.now) || 0, Number(r.prev) || 0);
    }))), 5).max;
    var alertPct = opts.alertPct == null ? 5 : opts.alertPct;
    var legend = '<div class="yc-legend"><span><i class="is-old"></i>上次同口径</span>' +
      '<span><i class="is-now"></i>当天</span>' +
      '<span><i class="is-alert"></i>变化超过 ' + esc(pct(alertPct, 0)) + '</span></div>';

    var body = valid.map(function (r) {
      if(!known(r.now))return '<div class="yc-dot-row is-missing"><div class="yc-dot-label"><strong>'+esc(r.label)+'</strong><small>缺少生产或计量依据</small></div><div class="yc-dot-track"></div><div class="yc-dot-value">待补</div></div>';
      var now = Number(r.now), prev = known(r.prev)?Number(r.prev):NaN;
      var hasPrev = isFinite(prev) && prev > 0;
      var change = known(r.change_pct)?Number(r.change_pct):null;
      var alert = r.alert === true;
      var x1 = hasPrev ? Math.min(100, prev / max * 100) : 0;
      var x2 = Math.min(100, now / max * 100);
      var left = Math.min(x1, x2), width = Math.abs(x2 - x1);
      return '<div class="yc-dot-row"><div class="yc-dot-label"><strong>' + esc(r.label) + '</strong><small class="' + (alert ? 'alert' : '') + '">' +
        (change == null ? '缺上次数据' : (change > 0 ? '+' : '') + num(change, 1) + '%' + (alert ? ' · 需核对' : '')) +
        '</small></div>' +
        '<div class="yc-dot-track">' +
        (hasPrev ? '<span class="yc-dot-line' + (alert ? ' alert' : '') + '" data-yc-left="' + left.toFixed(2) + '" data-yc-w="' + width.toFixed(2) + '"></span>' : '') +
        (hasPrev ? '<span class="yc-dot-mark old" data-yc-left="' + x1.toFixed(2) + '" title="上次 ' + esc(num(prev, 2)) + '"></span>' : '') +
        '<span class="yc-dot-mark now' + (alert ? ' alert' : '') + '" data-yc-left="' + x2.toFixed(2) + '" title="当天 ' + esc(num(now, 2)) + '"></span>' +
        '</div><div class="yc-dot-value">' + esc(num(now, 2)) + '</div></div>';
    }).join('');

    var plot = document.createElement('div');
    plot.className = 'yc-plot';
    plot.innerHTML = legend + '<div class="yc-dot">' + body + '</div>' +
      '<div class="yc-dot-scale"><span>0</span><span>' + esc(num(max, 1) + ' ' + (opts.unit || 'kg/kg')) + '</span></div>';
    root.appendChild(plot);
    finish(root, opts);
  }

  /* ---------------- 竖向柱状图 ---------------- */
  function drawBar(root, opts, W) {
    var raw = opts.data || [];
    var data = raw.filter(function (d) { return known(d.value); }).map(function (d) {
      return { label: d.label, value: Number(d.value) };
    });
    if (!data.length) {
      empty(root, { emptyTitle: opts.emptyTitle || '所选范围暂无数据', emptyHint: opts.emptyHint || '无单据与待补不按0计算；请先核对登记与复核进度。' });
      if (opts.caption) {
        var caption = document.createElement('p');
        caption.className = 'yc-caption';
        caption.textContent = opts.caption;
        root.appendChild(caption);
      }
      return;
    }
    var axisFormat = axisFormatter(opts);
    var valueFormat = opts.type === 'cents' ? function (v) { return compactMoney(v); } : function (v) { return num(v, 0) + (opts.unit ? ' ' + opts.unit : ''); };
    var rows = data.slice().sort(function (a, b) { return b.value - a.value; });
    var maxValue = Math.max.apply(null, rows.map(function (r) { return r.value; }).concat([0]));
    var scale = niceScale(0, maxValue, 4);
    var H = W < 560 ? 268 : 318;
    var M = { l: W < 560 ? 58 : 74, r: W < 560 ? 22 : 32, t: W < 560 ? 38 : 40, b: W < 560 ? 88 : 84 };
    var slotW = W < 560 ? 40 : 46;
    var chartW = Math.max(W, M.l + M.r + rows.length * slotW);
    var plotW = chartW - M.l - M.r, plotH = H - M.t - M.b, base = M.t + plotH;
    var y = function (v) { return M.t + plotH - (Number(v) - scale.min) / (scale.max - scale.min) * plotH; };
    var slot = plotW / rows.length, barW = Math.max(10, Math.min(52, slot * 0.58));
    var grid = scale.ticks.map(function (t) {
      return '<line x1="' + M.l + '" x2="' + (chartW - M.r) + '" y1="' + y(t).toFixed(1) + '" y2="' + y(t).toFixed(1) + '" class="yc-bar-grid"/>' +
        '<text x="' + (M.l - 8) + '" y="' + (y(t) + 4).toFixed(1) + '" text-anchor="end" class="yc-bar-axis">' + esc(axisFormat(t)) + '</text>';
    }).join('');
    var bars = rows.map(function (r, i) {
      var top = y(r.value), h = Math.max(0, base - top);
      var x = M.l + slot * i + (slot - barW) / 2;
      var tx = x + barW / 2, ty = base + 16;
      var labelLines = wrapChars(r.label, W < 560 ? 4 : 5).slice(0, 2);
      var label = labelLines.map(function (line, j) {
        return '<text x="' + tx.toFixed(1) + '" y="' + (ty + j * 13) + '" text-anchor="middle" class="yc-bar-label">' + esc(line) + '</text>';
      }).join('');
      return '<rect x="' + x.toFixed(1) + '" y="' + top.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + h.toFixed(1) + '" rx="3" class="yc-bar-rect"><title>' + esc(r.label + '：' + (opts.type === 'cents' ? money(r.value) : num(r.value, 2) + (opts.unit ? ' ' + opts.unit : ''))) + '</title></rect>' +
        '<text x="' + tx.toFixed(1) + '" y="' + Math.max(12, top - 6).toFixed(1) + '" text-anchor="middle" class="yc-bar-value">' + esc(valueFormat(r.value)) + '</text>' + label;
    }).join('');
    var plot = document.createElement('div');
    plot.className = 'yc-plot yc-plot-scroll';
    plot.innerHTML = '<svg viewBox="0 0 ' + chartW + ' ' + H + '" width="' + chartW + '" height="' + H + '" role="img" aria-label="' + esc(opts.caption || '柱状图') + '">' +
      grid + '<line x1="' + M.l + '" x2="' + (chartW - M.r) + '" y1="' + base + '" y2="' + base + '" class="yc-bar-base"/>' + bars + '</svg>';
    root.appendChild(plot);
    finish(root, opts);
  }

  global.YC = {
    destroy:function(root){if(root&&root.__ycRO)root.__ycRO.disconnect();if(root){delete root.__ycRO;delete root.__yc;}},
    line: function (root, opts) { mount(root, 'line', opts); },
    waterfall: function (root, opts) { mount(root, 'waterfall', opts); },
    rank: function (root, opts) { mount(root, 'rank', opts); },
    bar: function (root, opts) { mount(root, 'bar', opts); },
    composition: function (root, opts) { mount(root, 'composition', opts); },
    dotRange: function (root, opts) { mount(root, 'dot', opts); },
    fmt: { money: money, compactMoney: compactMoney, axisMoney: axisMoney, num: num, pct: pct },
    niceScale: niceScale
  };
})(window);
