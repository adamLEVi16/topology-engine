/* ============================================================
   TeamBuy demo — buyer team board
   Pick one active partner and one silent partner; the board runs
   the same fit checks a human would, including the failing ones.

   All profiles below are illustrative placeholders.
   ============================================================ */
(function () {
  "use strict";

  /* ---------------- data ---------------- */

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
    { id: "S-031", name: "Priya R.", min: 250000, max: 600000, verified: true,
      sectors: ["HVAC", "Plumbing", "Electrical"], regions: ["Southwest", "National"],
      seat: false, reporting: "Quarterly" },

    { id: "S-036", name: "Hal B.", min: 150000, max: 300000, verified: true,
      sectors: ["Landscaping", "Pest control"], regions: ["Southeast"],
      seat: true, reporting: "Monthly" },

    { id: "S-042", name: "Junie L.", min: 400000, max: 900000, verified: true,
      sectors: ["Plumbing", "Electrical"], regions: ["Midwest", "National"],
      seat: false, reporting: "Quarterly" },

    { id: "S-050", name: "Owen T.", min: 75000, max: 200000, verified: true,
      sectors: ["HVAC", "Plumbing", "Electrical", "Landscaping", "Pest control"],
      regions: ["Texas"], seat: false, reporting: "Quarterly" },

    { id: "S-057", name: "Marta S.", min: 500000, max: 1200000, verified: true,
      sectors: ["HVAC", "Electrical"], regions: ["National"],
      seat: true, reporting: "Monthly" }
  ];

  var SBA_DOWN = 0.10;         // minimum equity injection, SBA 7(a)
  var SBA_LOAN_CAP = 5000000;  // maximum 7(a) loan
  var FOCUS_MAX = 6000000;     // the deal band this platform works in

  /* ---------------- formatting ---------------- */

  function money(n) {
    if (n >= 1000000) {
      var m = n / 1000000;
      return "$" + (m >= 10 ? m.toFixed(1) : m.toFixed(2)).replace(/\.?0+$/, "") + "M";
    }
    if (n >= 1000) return "$" + Math.round(n / 1000) + "K";
    return "$" + n;
  }
  function exact(n) { return "$" + n.toLocaleString("en-US"); }
  function overlap(a, b) { return a.filter(function (x) { return b.indexOf(x) !== -1; }); }

  /* ---------------- state ---------------- */

  var pickedOp = null;
  var pickedInv = null;

  /* ---------------- card rendering ---------------- */

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
    b.addEventListener("click", function () {
      pickedOp = pickedOp === o ? null : o;
      sync();
    });
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
    b.addEventListener("click", function () {
      pickedInv = pickedInv === v ? null : v;
      sync();
    });
    return b;
  }

  /* ---------------- fit checks ---------------- */

  function evaluate(o, v) {
    var checks = [];
    var blocking = false;

    var sec = overlap(o.sectors, v.sectors);
    if (sec.length) {
      checks.push(["pass", "Sector match on <strong>" + sec.join(" and ") + "</strong>."]);
    } else {
      blocking = true;
      checks.push(["fail", "No sector overlap. " + o.name.split(" ")[0] + " runs " +
        o.sectors.join("/") + "; " + v.name.split(" ")[0] + " backs " + v.sectors.join("/") + "."]);
    }

    var reg = overlap(o.regions, v.regions);
    if (reg.length || v.regions.indexOf("National") !== -1) {
      checks.push(["pass", "Geography works — " +
        (reg.length ? reg.join(", ") : "capital is national") + "."]);
    } else {
      blocking = true;
      checks.push(["fail", "Geography conflict. The operator is in " + o.regions.join("/") +
        "; this capital only works in " + v.regions.join("/") + "."]);
    }

    if (v.seat && o.control === "full") {
      blocking = true;
      checks.push(["fail", "Control conflict. " + v.name.split(" ")[0] +
        " wants a board seat; " + o.name.split(" ")[0] +
        " wants full operational control. Settle this before anything else."]);
    } else if (v.seat) {
      checks.push(["pass", "Both sides accept a board seat and " +
        v.reporting.toLowerCase() + " reporting."]);
    } else {
      checks.push(["pass", "Silent by agreement — no operating role, " +
        v.reporting.toLowerCase() + " reporting."]);
    }

    var equity = o.capital + v.max;
    var byEquity = equity / SBA_DOWN;
    var byLoanCap = equity + SBA_LOAN_CAP;
    var max = Math.min(byEquity, byLoanCap);

    if (byLoanCap < byEquity) {
      checks.push(["warn", "The $5M SBA 7(a) loan cap binds before the cash does — " +
        "beyond " + money(max) + " this team needs seller financing or a second lender."]);
    }
    if (max > FOCUS_MAX) {
      checks.push(["warn", "This team can reach past the $1M–$6M band TeamBuy works in. " +
        "Deals that size usually go to a search fund."]);
    }
    if (v.max < v.min * 1.2 && o.capital < 50000) {
      checks.push(["warn", "Thin operator contribution. Sellers read a small buy-in as " +
        "low commitment, whatever the cap table says."]);
    }

    return { checks: checks, blocking: blocking, equity: equity, max: max };
  }

  /* ---------------- readout ---------------- */

  var readout = document.getElementById("readout");

  function renderReadout() {
    if (!pickedOp || !pickedInv) {
      var need = !pickedOp && !pickedInv ? "an operator and a capital partner"
               : !pickedOp ? "an operator" : "a capital partner";
      readout.innerHTML =
        '<p class="ro-label">Team readout</p>' +
        '<p class="ro-empty">Select ' + need + " to build a team. " +
        "The board will size what they can buy and flag what would break the partnership.</p>";
      return;
    }

    var r = evaluate(pickedOp, pickedInv);

    var figure = r.blocking
      ? '<div class="ro-figure is-blocked">' +
          '<p class="ro-fig-label">Not a team yet</p>' +
          '<p class="ro-fig-num">' + money(r.equity) + " on the table</p>" +
          '<p class="ro-fig-note">The capital works. The terms do not — see the flags below.</p>' +
        "</div>"
      : '<div class="ro-figure">' +
          '<p class="ro-fig-label">Combined equity injection</p>' +
          '<p class="ro-fig-num">' + exact(r.equity) + "</p>" +
          '<p class="ro-fig-note">Supports a purchase up to <strong>' + money(r.max) +
          "</strong> at 10% down.</p>" +
        "</div>";

    readout.innerHTML =
      '<p class="ro-label">Team readout</p>' +
      '<p class="ro-team">' + pickedOp.name + " + " + pickedInv.name + "</p>" +
      '<p class="ro-sub">' + pickedOp.role + " · " + pickedOp.years +
        " years · files " + pickedOp.id + " / " + pickedInv.id + "</p>" +
      figure +
      '<ul class="checks">' + r.checks.map(function (c) {
        var mark = c[0] === "pass" ? "&check;" : c[0] === "warn" ? "!" : "&times;";
        return '<li class="check check-' + c[0] + '">' +
               '<span class="check-mark" aria-hidden="true">' + mark + "</span>" +
               '<span class="check-body">' + c[1] + "</span></li>";
      }).join("") + "</ul>" +
      '<p class="ro-foot">' + (r.blocking
        ? "Resolve the flags, then sign partnership terms."
        : "Next: sign partnership terms, then approach brokers.") + "</p>";
  }

  function sync() {
    opButtons.forEach(function (b, i) {
      b.setAttribute("aria-pressed", OPERATORS[i] === pickedOp ? "true" : "false");
    });
    invButtons.forEach(function (b, i) {
      b.setAttribute("aria-pressed", INVESTORS[i] === pickedInv ? "true" : "false");
    });
    renderReadout();
  }

  /* ---------------- mount ---------------- */

  var opWrap = document.getElementById("ops");
  var invWrap = document.getElementById("cap");
  var opButtons = OPERATORS.map(opCard);
  var invButtons = INVESTORS.map(invCard);

  opButtons.forEach(function (b) { opWrap.appendChild(b); });
  invButtons.forEach(function (b) { invWrap.appendChild(b); });

  // open on a pairing that shows the product working
  pickedOp = OPERATORS[0];
  pickedInv = INVESTORS[0];
  sync();
})();
