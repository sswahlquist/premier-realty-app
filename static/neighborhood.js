/* Premier Realty — Neighborhood Intelligence */

// ── Mode toggle ────────────────────────────────────────────────
const modeSingle  = document.getElementById("modeSingle");
const modeCompare = document.getElementById("modeCompare");
const formSingle  = document.getElementById("formSingle");
const formCompare = document.getElementById("formCompare");

modeSingle.addEventListener("click", () => {
  modeSingle.classList.add("mode-btn--active");
  modeCompare.classList.remove("mode-btn--active");
  formSingle.style.display  = "block";
  formCompare.style.display = "none";
  resetPage();
});
modeCompare.addEventListener("click", () => {
  modeCompare.classList.add("mode-btn--active");
  modeSingle.classList.remove("mode-btn--active");
  formCompare.style.display = "block";
  formSingle.style.display  = "none";
  resetPage();
});

// ── UI state ───────────────────────────────────────────────────
function showLoading(msg) {
  document.getElementById("loadingText").textContent = msg || "Analyzing neighborhood…";
  document.getElementById("nbhdLoading").style.display = "flex";
  document.getElementById("nbhdError").style.display   = "none";
  document.getElementById("singleResult").style.display  = "none";
  document.getElementById("compareResult").style.display = "none";
}
function showError(msg) {
  document.getElementById("errorMsg").textContent = msg;
  document.getElementById("nbhdLoading").style.display = "none";
  document.getElementById("nbhdError").style.display   = "flex";
}
function resetPage() {
  document.getElementById("nbhdLoading").style.display   = "none";
  document.getElementById("nbhdError").style.display     = "none";
  document.getElementById("singleResult").style.display  = "none";
  document.getElementById("compareResult").style.display = "none";
}

// ── Fit badge ──────────────────────────────────────────────────
function fitBadge(fit) {
  const map = {
    "Strong Fit":   { cls: "fit--strong",   icon: "★★★" },
    "Good Fit":     { cls: "fit--good",     icon: "★★☆" },
    "Moderate Fit": { cls: "fit--moderate", icon: "★☆☆" },
    "Poor Fit":     { cls: "fit--poor",     icon: "✗✗✗" },
  };
  const found = Object.keys(map).find(k => fit && fit.startsWith(k));
  const info  = found ? map[found] : { cls: "fit--moderate", icon: "—" };
  return `<span class="fit-badge ${info.cls}">${info.icon} ${found || fit}</span>`;
}

// ── Winner badge ───────────────────────────────────────────────
function winnerBadge(winner, nameA, nameB) {
  if (!winner) return "";
  const isTie = winner.toLowerCase() === "tie";
  const isA   = winner === nameA;
  return `<span class="winner-badge ${isTie ? "winner--tie" : isA ? "winner--a" : "winner--b"}">
    ${isTie ? "🤝 Tie" : (isA ? "🏆 " + nameA : "🏆 " + nameB)}
  </span>`;
}

// ── Build profile HTML ─────────────────────────────────────────
function buildProfile(profile, name, city, compact) {
  const bf = profile.BEST_FOR || {};
  const bfKeys = ["FAMILIES", "YOUNG_PROFESSIONALS", "RETIREES", "INVESTORS"];
  const bfLabels = { FAMILIES: "👨‍👩‍👧 Families", YOUNG_PROFESSIONALS: "💼 Young Professionals", RETIREES: "🌿 Retirees", INVESTORS: "📈 Investors" };

  const prosCons = (list) => (list || []).map(item => `<li>${item}</li>`).join("");

  return `
    <!-- Vibe -->
    <div class="pcard pcard--wide">
      <div class="pcard-header"><span class="pcard-icon">🏘</span><h3>Neighborhood Vibe</h3></div>
      <p class="pcard-body">${profile.VIBE || "—"}</p>
    </div>

    <!-- Buyer Profile -->
    <div class="pcard">
      <div class="pcard-header"><span class="pcard-icon">👤</span><h3>Typical Buyer</h3></div>
      <p class="pcard-body">${profile.BUYER_PROFILE || "—"}</p>
    </div>

    <!-- Price Trends -->
    <div class="pcard">
      <div class="pcard-header"><span class="pcard-icon">📈</span><h3>Price Trends</h3></div>
      <p class="pcard-body">${profile.PRICE_TRENDS || "—"}</p>
    </div>

    <!-- Pros & Cons Buyers -->
    <div class="pcard pcard--split">
      <div class="pcard-header pcard-header--buyer"><span class="pcard-icon">🏠</span><h3>For Buyers</h3></div>
      <div class="pcard-split-body">
        <div class="split-col split-col--pros">
          <p class="split-label">✅ Pros</p>
          <ul class="pc-list">${prosCons(profile.PROS_BUYERS)}</ul>
        </div>
        <div class="split-col split-col--cons">
          <p class="split-label">❌ Cons</p>
          <ul class="pc-list">${prosCons(profile.CONS_BUYERS)}</ul>
        </div>
      </div>
    </div>

    <!-- Pros & Cons Sellers -->
    <div class="pcard pcard--split">
      <div class="pcard-header pcard-header--seller"><span class="pcard-icon">🏷</span><h3>For Sellers</h3></div>
      <div class="pcard-split-body">
        <div class="split-col split-col--pros">
          <p class="split-label">✅ Pros</p>
          <ul class="pc-list">${prosCons(profile.PROS_SELLERS)}</ul>
        </div>
        <div class="split-col split-col--cons">
          <p class="split-label">❌ Cons</p>
          <ul class="pc-list">${prosCons(profile.CONS_SELLERS)}</ul>
        </div>
      </div>
    </div>

    <!-- Schools -->
    <div class="pcard">
      <div class="pcard-header"><span class="pcard-icon">🎓</span><h3>Schools</h3></div>
      <p class="pcard-body">${profile.SCHOOLS || "—"}</p>
    </div>

    <!-- Walkability -->
    <div class="pcard">
      <div class="pcard-header"><span class="pcard-icon">🚶</span><h3>Walkability & Transit</h3></div>
      <p class="pcard-body">${profile.WALKABILITY || "—"}</p>
    </div>

    <!-- Rental Yield -->
    <div class="pcard">
      <div class="pcard-header"><span class="pcard-icon">💰</span><h3>Rental Yield</h3></div>
      <p class="pcard-body">${profile.RENTAL_YIELD || "—"}</p>
    </div>

    <!-- Best For -->
    <div class="pcard pcard--bestfor">
      <div class="pcard-header"><span class="pcard-icon">🌟</span><h3>Best For</h3></div>
      <div class="bestfor-grid">
        ${bfKeys.map(k => {
          const entry = bf[k] || {};
          return `
            <div class="bestfor-item">
              <div class="bestfor-top">
                <span class="bestfor-label">${bfLabels[k]}</span>
                ${fitBadge(entry.fit || "")}
              </div>
              <p class="bestfor-note">${entry.note || ""}</p>
            </div>`;
        }).join("")}
      </div>
    </div>
  `;
}

// ── Single analyze ─────────────────────────────────────────────
document.getElementById("btnSingle").addEventListener("click", async () => {
  const name = document.getElementById("s_name").value.trim();
  const city = document.getElementById("s_city").value.trim();
  if (!name || !city) {
    alert("Please enter both a neighborhood name and city.");
    return;
  }
  showLoading(`Analyzing ${name}, ${city}…`);
  try {
    const res  = await fetch("/neighborhood/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, city }),
    });
    const data = await res.json();
    if (data.error) { showError(data.error); return; }

    document.getElementById("resultCity").textContent    = data.city;
    document.getElementById("resultName").textContent    = data.name;
    document.getElementById("resultTagline").textContent = data.profile.TAGLINE || "";
    document.getElementById("profileGrid").innerHTML     = buildProfile(data.profile, data.name, data.city);

    document.getElementById("nbhdLoading").style.display  = "none";
    document.getElementById("singleResult").style.display = "block";
    document.getElementById("singleResult").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    showError("Connection error. Please check the server is running and try again.");
  }
});

// Enter key support
["s_name", "s_city"].forEach(id => {
  document.getElementById(id).addEventListener("keydown", e => {
    if (e.key === "Enter") document.getElementById("btnSingle").click();
  });
});

// ── Compare ────────────────────────────────────────────────────
document.getElementById("btnCompare").addEventListener("click", async () => {
  const n1 = document.getElementById("c1_name").value.trim();
  const c1 = document.getElementById("c1_city").value.trim();
  const n2 = document.getElementById("c2_name").value.trim();
  const c2 = document.getElementById("c2_city").value.trim();
  if (!n1 || !c1 || !n2 || !c2) {
    alert("Please fill in both neighborhoods and cities.");
    return;
  }
  showLoading(`Comparing ${n1} vs ${n2}…`);
  try {
    const res  = await fetch("/neighborhood/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name1: n1, city1: c1, name2: n2, city2: c2 }),
    });
    const data = await res.json();
    if (data.error) { showError(data.error); return; }

    const cmp = data.comparison || {};

    // Verdict bar
    const verdictKeys = [
      { key: "WINNER_BUYERS",    label: "Best for Buyers",    icon: "🏠" },
      { key: "WINNER_SELLERS",   label: "Best for Sellers",   icon: "🏷" },
      { key: "WINNER_INVESTORS", label: "Best for Investors", icon: "📈" },
    ];
    document.getElementById("verdictBar").innerHTML = `
      <div class="verdict-cards">
        ${verdictKeys.map(v => {
          const entry = cmp[v.key] || {};
          return `
            <div class="verdict-card">
              <p class="verdict-label">${v.icon} ${v.label}</p>
              ${winnerBadge(entry.winner, n1, n2)}
              <p class="verdict-note">${entry.note || ""}</p>
            </div>`;
        }).join("")}
        ${(cmp.KEY_DIFFERENCES || []).length ? `
        <div class="verdict-card verdict-card--diffs">
          <p class="verdict-label">🔑 Key Differences</p>
          <ul class="diffs-list">
            ${(cmp.KEY_DIFFERENCES || []).map(d => `<li>${d}</li>`).join("")}
          </ul>
        </div>` : ""}
      </div>
    `;

    // Side-by-side profiles
    document.getElementById("compareGrid").innerHTML = `
      <div class="compare-profile">
        <div class="compare-profile-header compare-profile-header--a">
          <span class="compare-badge">A</span>
          <div>
            <p class="compare-profile-city">${data.a.city}</p>
            <p class="compare-profile-name">${data.a.name}</p>
            <p class="compare-profile-tagline">${data.a.profile.TAGLINE || ""}</p>
          </div>
        </div>
        <div class="profile-grid profile-grid--compact">${buildProfile(data.a.profile, data.a.name, data.a.city, true)}</div>
      </div>
      <div class="compare-profile">
        <div class="compare-profile-header compare-profile-header--b">
          <span class="compare-badge compare-badge--b">B</span>
          <div>
            <p class="compare-profile-city">${data.b.city}</p>
            <p class="compare-profile-name">${data.b.name}</p>
            <p class="compare-profile-tagline">${data.b.profile.TAGLINE || ""}</p>
          </div>
        </div>
        <div class="profile-grid profile-grid--compact">${buildProfile(data.b.profile, data.b.name, data.b.city, true)}</div>
      </div>
    `;

    document.getElementById("nbhdLoading").style.display   = "none";
    document.getElementById("compareResult").style.display = "block";
    document.getElementById("compareResult").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    showError("Connection error. Please check the server is running and try again.");
  }
});

["c1_name","c1_city","c2_name","c2_city"].forEach(id => {
  document.getElementById(id).addEventListener("keydown", e => {
    if (e.key === "Enter") document.getElementById("btnCompare").click();
  });
});
