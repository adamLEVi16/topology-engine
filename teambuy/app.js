/* ============================================================
   TeamBuy demo

   Three interactive pieces:
     1. The capital stack — two sliders, one stacked bar
     2. The buyer-team board — pair an operator with capital
     3. Reveal / counter / sticky-nav chrome

   All profiles and figures are illustrative placeholders.
   ============================================================ */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ═══════════ shared financing assumptions ═══════════ */

  var SBA_DOWN = 0.10;         // minimum equity injection, SBA 7(a)
  var SBA_LOAN_CAP = 5000000;  // maximum 7(a) loan
  var FOCUS_MAX = 6000000;     // the band this platform works in

  /* Senior → junior. Order is the stack order and the legend order. */
  var SERIES = [
    { key: "loan",   label: "SBA 7(a) loan",       cls: "seg-loan",   sw: "--s-loan" },
    { key: "note",   label: "Seller note",         cls: "seg-note",   sw: "--s-note" },
    { key: "equity", label: "Silent partner",      cls: "seg-equity", sw: "--s-equity" },
    { key: "cash",   label: "Operator's own cash", cls: "seg-cash",   sw: "--s-cash" }
  ];

  /* ═══════════ formatting ═══════════ */

  function money(n) {
    if (n >= 1000000) {
      var m = n / 1000000;
      return "$" + (m >= 10 ? m.toFixed(1) : m.toFixed(2)).replace(/\.?0+$/, "") + "M";
    }
    if (n >= 1000) return "$" + Math.round(n / 1000) + "K";
    return "$" + Math.round(n);
  }
  function exact(n) { return "$" + Math.round(n).toLocaleString("en-US"); }
  function pct(n, total) { return total ? (n / total * 100).toFixed(1) + "%" : "0%"; }
  function overlap(a, b) { return a.filter(function (x) { return b.indexOf(x) !== -1; }); }

  /* ═══════════ capital stack math ═══════════ */

  /* Calculator: pick a price, the operator brings what cash they have,
     a silent partner covers the rest of the required injection. */
  function stackFromPrice(price, operatorCash) {
    var injection = price * SBA_DOWN;
    var cash = Math.min(operatorCash, injection);
    var equity = injection - cash;
    var loan = Math.min(price - injection, SBA_LOAN_CAP);
    var note = Math.max(0, price - injection - loan);
    return { total: price, loan: loan, note: note, equity: equity, cash: cash, injection: injection };
  }

  /* Board: equity is fixed by who is on the team, so the price is derived. */
  function stackFromTeam(op, inv) {
    var injection = op.capital + inv.max;
    var price = Math.min(injection / SBA_DOWN, injection + SBA_LOAN_CAP);
    var loan = Math.min(price - injection, SBA_LOAN_CAP);
    var note = Math.max(0, price - injection - loan);
    return {
      total: price, loan: loan, note: note,
      equity: inv.max, cash: op.capital, injection: injection
    };
  }

  /* ═══════════ chart rendering ═══════════ */

  var stackEl   = document.getElementById("stack");
  var legendEl  = document.getElementById("legend");
  var subEl     = document.getElementById("chart-sub");
  var descEl    = document.getElementById("stack-desc");
  var tableEl   = document.getElementById("stack-table");
  var annotEl   = document.getElementById("annot");
  var chartEl   = document.getElementById("chart");

  var tip = document.createElement("div");
  tip.className = "tip";
  tip.hidden = true;
  if (chartEl) chartEl.appendChild(tip);

  function showTip(seg, text) {
    tip.textContent = text;
    tip.hidden = false;
    var cb = chartEl.getBoundingClientRect();
    var sb = seg.getBoundingClientRect();
    var x = sb.left - cb.left + sb.width / 2;
    tip.style.left = Math.max(8, Math.min(cb.width - 8, x)) + "px";
    tip.style.top = (sb.top - cb.top - 10) + "px";
  }

  function renderStack(s) {
    stackEl.innerHTML = "";
    var parts = SERIES.map(function (def) {
      return { def: def, value: s[def.key] };
    }).filter(function (p) { return p.value > 0; });

    parts.forEach(function (p) {
      var seg = document.createElement("div");
      seg.className = "seg " + p.def.cls;
      seg.style.flex = p.value + " 0 0";
      var share = p.value / s.total;
      if (share >= 0.11) {
        seg.innerHTML =
          '<span class="seg-val">' + money(p.value) + "</span>" +
          '<span class="seg-pct">' + pct(p.value, s.total) + "</span>";
      } else if (share >= 0.055) {
        seg.innerHTML = '<span class="seg-val">' + money(p.value) + "</span>";
      }
      var label = p.def.label + " — " + exact(p.value) + " (" + pct(p.value, s.total) + ")";
      seg.addEventListener("mouseenter", function () { showTip(seg, label); });
      seg.addEventListener("mouseleave", function () { tip.hidden = true; });
      stackEl.appendChild(seg);
    });

    /* Annotate the band the whole section is about: the equity injection.
       Everything left of the bracket is money the operator never has to find. */
    var debt = s.loan + s.note;
    annotEl.innerHTML =
      '<div class="annot-sp" style="flex:' + (debt || 0.0001) + ' 0 0"></div>' +
      '<div class="annot-br" style="flex:' + (s.equity + s.cash) + ' 0 0">' +
        '<span class="annot-label">Equity injection · ' + pct(s.injection, s.total) +
        " · " + exact(s.injection) + "</span>" +
      "</div>";

    legendEl.innerHTML = SERIES.map(function (def) {
      var v = s[def.key];
      return '<li><span class="sw" style="background:var(' + def.sw + ')"></span>' +
             def.label + '<span class="lg-val">' + (v > 0 ? exact(v) : "—") + "</span></li>";
    }).join("");

    subEl.textContent = money(s.total) + " total";
    descEl.textContent = "Capital stack for a " + exact(s.total) + " purchase: " +
      SERIES.filter(function (d) { return s[d.key] > 0; }).map(function (d) {
        return d.label + " " + exact(s[d.key]) + " (" + pct(s[d.key], s.total) + ")";
      }).join("; ") + ".";

    tableEl.innerHTML =
      "<thead><tr><th>Source</th><th>Amount</th><th>Share</th></tr></thead><tbody>" +
      SERIES.map(function (d) {
        return "<tr><td>" + d.label + "</td><td>" + (s[d.key] > 0 ? exact(s[d.key]) : "—") +
               "</td><td>" + pct(s[d.key], s.total) + "</td></tr>";
      }).join("") +
      "<tr><td>Total purchase price</td><td>" + exact(s.total) + "</td><td>100%</td></tr>" +
      "</tbody>";
  }

  /* ═══════════ calculator ═══════════ */

  var inPrice = document.getElementById("in-price");
  var inCash  = document.getElementById("in-cash");
  var outPrice = document.getElementById("out-price");
  var outCash  = document.getElementById("out-cash");
  var hintEl   = document.getElementById("calc-hint");

  function syncCalc() {
    var price = +inPrice.value;
    var cash = +inCash.value;
    var s = stackFromPrice(price, cash);

    outPrice.textContent = exact(price);
    outCash.textContent = exact(cash);
    renderStack(s);

    var hint;
    if (s.equity <= 0) {
      hint = "At this price the operator can cover the whole " + exact(s.injection) +
             " injection alone — <strong>no silent partner needed</strong>. " +
             "That is the happy case, and it is rare.";
    } else {
      hint = "The operator brings <strong>" + exact(s.cash) + "</strong> — " +
             pct(s.cash, s.total) + " of the purchase. A silent partner covers the " +
             "remaining <strong>" + exact(s.equity) + "</strong> of the injection. " +
             "The bank covers the other " + pct(s.loan, s.total) + ".";
    }
    if (s.note > 0) {
      hint += " Past the $5M loan cap, <strong>" + exact(s.note) +
              "</strong> has to come from a seller note or a second lender.";
    }
    hintEl.innerHTML = hint;
  }

  if (inPrice && inCash) {
    inPrice.addEventListener("input", syncCalc);
    inCash.addEventListener("input", syncCalc);
    syncCalc();
  }

  /* ═══════════ board data ═══════════ */

  var OPERATORS = [
    { id: "A-014", name: "Marcus D.", role: "HVAC service manager", years: 14,
      pl: 6200000, crew: 22, capital: 85000,
      sectors: ["HVAC", "Plumbing"], regions: ["Southwest"], control: "full" },

    { id: "A-022", name: "Dana W.", role: "Commercial landscaping ops director", years: 9,
      pl: 3400000, crew: 31, capital: 40000,
      sectors: ["Landscaping"], regions: ["Southeast"], control: "shared" },

    { id: "A-031", name: "Toby N.", role: "Plumbing general manager", years: 17,
      pl: 8100000, crew: 40, capital: 150000,
      sectors: ["Plumbing", "Electrical"], regions: ["Midwest"], control: "full" },

    { id: "A-038", name: "Renee A.", role: "Electrical branch manager", years: 11,
      pl: 4900000, crew: 18, capital: 60000,
      sectors: ["Electrical"], regions: ["Texas"], control: "shared" },

    { id: "A-045", name: "Sam K.", role: "Pest control regional manager", years: 8,
      pl: 2700000, crew: 14, capital: 25000,
      sectors: ["Pest control"], regions: ["Southwest"], control: "shared" }
  ];

  var INVESTORS = [
    { id: "S-031", name: "Priya R.", min: 250000, max: 600000,
      sectors: ["HVAC", "Plumbing", "Electrical"], regions: ["Southwest", "National"],
      seat: false, reporting: "Quarterly" },

    { id: "S-036", name: "Hal B.", min: 150000, max: 300000,
      sectors: ["Landscaping", "Pest control"], regions: ["Southeast"],
      seat: true, reporting: "Monthly" },

    { id: "S-042", name: "Junie L.", min: 400000, max: 900000,
      sectors: ["Plumbing", "Electrical"], regions: ["Midwest", "National"],
      seat: false, reporting: "Quarterly" },

    { id: "S-050", name: "Owen T.", min: 75000, max: 200000,
      sectors: ["HVAC", "Plumbing", "Electrical", "Landscaping", "Pest control"],
      regions: ["Texas"], seat: false, reporting: "Quarterly" },

    { id: "S-057", name: "Marta S.", min: 500000, max: 1200000,
      sectors: ["HVAC", "Electrical"], regions: ["National"],
      seat: true, reporting: "Monthly" }
  ];

  var pickedOp = null, pickedInv = null;

  function opCard(o) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "pick";
    b.setAttribute("aria-pressed", "false");
    b.innerHTML =
      '<span class="pick-name">' + o.name + "</span>" +
      '<span class="pick-meta">' + o.role + " · " + o.years + " yrs</span>" +
      '<span class="pick-stat">' + o.sectors.join(", ") + " · " + o.regions[0] +
      " · brings " + money(o.capital) + "</span>";
    b.addEventListener("click", function () { pickedOp = pickedOp === o ? null : o; syncBoard(); });
    return b;
  }

  function invCard(v) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "pick";
    b.setAttribute("aria-pressed", "false");
    b.innerHTML =
      '<span class="pick-name">' + v.name + "</span>" +
      '<span class="pick-meta">' + money(v.min) + " – " + money(v.max) +
      (v.seat ? " · wants a board seat" : " · no operating role") + "</span>" +
      '<span class="pick-stat">' + v.sectors.length + " sectors · " +
      v.regions.join(", ") + " · " + v.reporting + "</span>";
    b.addEventListener("click", function () { pickedInv = pickedInv === v ? null : v; syncBoard(); });
    return b;
  }

  /* ═══════════ fit checks ═══════════ */

  function evaluate(o, v) {
    var checks = [], blocking = false;
    var first = function (n) { return n.split(" ")[0]; };

    var sec = overlap(o.sectors, v.sectors);
    if (sec.length) {
      checks.push(["pass", "Sector match on <strong>" + sec.join(" and ") + "</strong>."]);
    } else {
      blocking = true;
      checks.push(["fail", "No sector overlap. " + first(o.name) + " runs " + o.sectors.join("/") +
        "; " + first(v.name) + " backs " + v.sectors.join("/") + "."]);
    }

    var reg = overlap(o.regions, v.regions);
    if (reg.length || v.regions.indexOf("National") !== -1) {
      checks.push(["pass", "Geography works — " + (reg.length ? reg.join(", ") : "capital is national") + "."]);
    } else {
      blocking = true;
      checks.push(["fail", "Geography conflict. The operator is in " + o.regions.join("/") +
        "; this capital only works in " + v.regions.join("/") + "."]);
    }

    if (v.seat && o.control === "full") {
      blocking = true;
      checks.push(["fail", "Control conflict. " + first(v.name) + " wants a board seat; " +
        first(o.name) + " wants full operational control. Settle this before anything else."]);
    } else if (v.seat) {
      checks.push(["pass", "Both sides accept a board seat and " + v.reporting.toLowerCase() + " reporting."]);
    } else {
      checks.push(["pass", "Silent by agreement — no operating role, " + v.reporting.toLowerCase() + " reporting."]);
    }

    var s = stackFromTeam(o, v);
    if (s.note > 0) {
      checks.push(["warn", "The $5M SBA 7(a) loan cap binds before the cash does — " +
        exact(s.note) + " would need a seller note or a second lender."]);
    }
    if (s.total > FOCUS_MAX) {
      checks.push(["warn", "This team can reach past the $1M–$6M band TeamBuy works in. " +
        "Deals that size usually go to a search fund."]);
    }
    if (o.capital / s.injection < 0.15) {
      checks.push(["warn", "Thin operator contribution — " + pct(o.capital, s.injection) +
        " of the injection. Sellers read a small buy-in as low commitment."]);
    }

    return { checks: checks, blocking: blocking, stack: s };
  }

  /* ═══════════ readout ═══════════ */

  var readout = document.getElementById("readout");

  function miniStack(s) {
    return '<div class="ro-stack" aria-hidden="true">' + SERIES.filter(function (d) {
      return s[d.key] > 0;
    }).map(function (d) {
      return '<span style="flex:' + s[d.key] + ' 0 0;background:var(' + d.sw + ')"></span>';
    }).join("") + "</div>";
  }

  function renderReadout() {
    if (!pickedOp || !pickedInv) {
      var need = !pickedOp && !pickedInv ? "an operator and a capital partner"
               : !pickedOp ? "an operator" : "a capital partner";
      readout.innerHTML =
        '<p class="ro-label">Team readout</p>' +
        '<p class="ro-empty">Select ' + need + ". The board will size what they can buy " +
        "and flag what would break the partnership.</p>";
      return;
    }

    var r = evaluate(pickedOp, pickedInv);
    var s = r.stack;

    var figure = r.blocking
      ? '<div class="ro-figure is-blocked">' +
          '<p class="ro-fig-label">Not a team yet</p>' +
          '<p class="ro-fig-num">' + money(s.injection) + " on the table</p>" +
          '<p class="ro-fig-note">The capital works. The terms do not — see the flags below.</p>' +
        "</div>"
      : '<div class="ro-figure">' +
          '<p class="ro-fig-label">Combined equity injection</p>' +
          '<p class="ro-fig-num">' + exact(s.injection) + "</p>" +
          '<p class="ro-fig-note">Supports a purchase up to <strong>' + money(s.total) +
          "</strong> at 10% down.</p>" +
        "</div>";

    readout.innerHTML =
      '<p class="ro-label">Team readout</p>' +
      '<p class="ro-team">' + pickedOp.name + " + " + pickedInv.name + "</p>" +
      '<p class="ro-sub">' + pickedOp.role + " · " + pickedOp.years + " years · files " +
        pickedOp.id + " / " + pickedInv.id + "</p>" +
      figure +
      (r.blocking ? "" : miniStack(s)) +
      '<div class="checks">' + r.checks.map(function (c) {
        var mark = c[0] === "pass" ? "&check;" : c[0] === "warn" ? "!" : "&times;";
        return '<div class="check check-' + c[0] + '">' +
               '<span class="check-mark" aria-hidden="true">' + mark + "</span>" +
               '<span class="check-body">' + c[1] + "</span></div>";
      }).join("") + "</div>" +
      '<p class="ro-foot">' + (r.blocking
        ? "Resolve the flags, then sign partnership terms."
        : "Next: sign partnership terms, then approach brokers.") + "</p>";
  }

  var opWrap = document.getElementById("ops");
  var invWrap = document.getElementById("cap");
  var opButtons = [], invButtons = [];

  function syncBoard() {
    opButtons.forEach(function (b, i) {
      b.setAttribute("aria-pressed", OPERATORS[i] === pickedOp ? "true" : "false");
    });
    invButtons.forEach(function (b, i) {
      b.setAttribute("aria-pressed", INVESTORS[i] === pickedInv ? "true" : "false");
    });
    renderReadout();
  }

  if (opWrap && invWrap) {
    opButtons = OPERATORS.map(opCard);
    invButtons = INVESTORS.map(invCard);
    opButtons.forEach(function (b) { opWrap.appendChild(b); });
    invButtons.forEach(function (b) { invWrap.appendChild(b); });
    pickedOp = OPERATORS[0];
    pickedInv = INVESTORS[0];
    syncBoard();
  }

  /* ═══════════ chrome: reveals, counters, sticky nav ═══════════ */

  var nav = document.getElementById("nav");
  if (nav) {
    var onScroll = function () { nav.classList.toggle("is-stuck", window.scrollY > 8); };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  var reveals = [].slice.call(document.querySelectorAll(".reveal"));
  if (reduceMotion || !("IntersectionObserver" in window)) {
    reveals.forEach(function (el) { el.classList.add("in"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var sibs = [].slice.call(e.target.parentNode.children);
        e.target.style.transitionDelay = (sibs.indexOf(e.target) * 70) + "ms";
        e.target.classList.add("in");
        io.unobserve(e.target);
      });
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.15 });
    reveals.forEach(function (el) { io.observe(el); });
  }

  var counters = [].slice.call(document.querySelectorAll("[data-count]"));
  if (counters.length && !reduceMotion && "IntersectionObserver" in window) {
    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var el = e.target;
        var target = +el.getAttribute("data-count");
        var pre = el.getAttribute("data-prefix") || "";
        var suf = el.getAttribute("data-suffix") || "";
        var start = performance.now(), dur = 700;
        var tick = function (now) {
          var t = Math.min(1, (now - start) / dur);
          var eased = 1 - Math.pow(1 - t, 3);
          el.textContent = pre + Math.round(target * eased) + suf;
          if (t < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
        cio.unobserve(el);
      });
    }, { threshold: 0.5 });
    counters.forEach(function (el) { cio.observe(el); });
  }
})();
