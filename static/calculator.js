/* Premier Realty — Mortgage Calculator */

// ── State ──────────────────────────────────────────────────────
let loanTerm    = 30;
let chatHistory = [];
let affordWaiting = false;

// ── Elements ───────────────────────────────────────────────────
const homePrice    = document.getElementById("homePrice");
const downPct      = document.getElementById("downPct");
const rate         = document.getElementById("rate");
const homePriceVal = document.getElementById("homePriceVal");
const downPctVal   = document.getElementById("downPctVal");
const downAmt      = document.getElementById("downAmt");
const rateVal      = document.getElementById("rateVal");

const elMonthly     = document.getElementById("monthlyPayment");
const elDown        = document.getElementById("downPaymentAmt");
const elLoan        = document.getElementById("loanAmount");
const elInterest    = document.getElementById("totalInterest");
const elTotal       = document.getElementById("totalCost");
const elPrincipalPct = document.getElementById("principalPct");
const elInterestPct  = document.getElementById("interestPct");
const costBarP      = document.getElementById("costBarPrincipal");
const costBarI      = document.getElementById("costBarInterest");
const amortBody     = document.getElementById("amortBody");

// ── Formatters ─────────────────────────────────────────────────
const fmtUSD = (n) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);

const fmtUSDdec = (n) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);

// ── Core mortgage math ─────────────────────────────────────────
function calcMonthly(principal, annualRate, years) {
  if (annualRate === 0) return principal / (years * 12);
  const r = annualRate / 100 / 12;
  const n = years * 12;
  return principal * (r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1);
}

function buildAmortization(principal, annualRate, years) {
  const r       = annualRate / 100 / 12;
  const n       = years * 12;
  const payment = calcMonthly(principal, annualRate, years);
  let balance   = principal;
  const rows    = [];
  for (let i = 1; i <= n; i++) {
    const interestPayment   = balance * r;
    const principalPayment  = payment - interestPayment;
    balance                -= principalPayment;
    rows.push({
      month:     i,
      payment,
      principal: principalPayment,
      interest:  interestPayment,
      balance:   Math.max(balance, 0),
    });
  }
  return rows;
}

// ── Update UI ──────────────────────────────────────────────────
function update() {
  const price    = parseFloat(homePrice.value);
  const pct      = parseFloat(downPct.value);
  const r        = parseFloat(rate.value);
  const down     = price * pct / 100;
  const loan     = price - down;
  const monthly  = calcMonthly(loan, r, loanTerm);
  const totalPay = monthly * loanTerm * 12;
  const totalInt = totalPay - loan;

  // Slider labels
  homePriceVal.textContent = fmtUSD(price);
  downPctVal.innerHTML     = `${pct}% <span class="slider-sub">= ${fmtUSD(down)}</span>`;
  rateVal.textContent      = `${r.toFixed(1)}%`;

  // Summary cards
  elMonthly.textContent  = fmtUSDdec(monthly);
  elDown.textContent     = fmtUSD(down);
  elLoan.textContent     = fmtUSD(loan);
  elInterest.textContent = fmtUSD(totalInt);
  elTotal.textContent    = fmtUSD(totalPay);

  // Cost bar
  const principalPct = Math.round((loan / totalPay) * 100);
  const interestPct  = 100 - principalPct;
  costBarP.style.width = principalPct + "%";
  costBarI.style.width = interestPct  + "%";
  elPrincipalPct.textContent = principalPct + "%";
  elInterestPct.textContent  = interestPct  + "%";

  // Amortization table — first 24 months
  const schedule = buildAmortization(loan, r, loanTerm);
  const first24  = schedule.slice(0, 24);
  amortBody.innerHTML = first24.map(row => `
    <tr>
      <td class="amort-mo">${row.month}</td>
      <td>${fmtUSDdec(row.payment)}</td>
      <td class="amort-principal">${fmtUSDdec(row.principal)}</td>
      <td class="amort-interest">${fmtUSDdec(row.interest)}</td>
      <td>${fmtUSD(row.balance)}</td>
    </tr>
  `).join("");
}

// ── Sliders ────────────────────────────────────────────────────
[homePrice, downPct, rate].forEach(el => el.addEventListener("input", update));

// ── Term toggle ────────────────────────────────────────────────
document.querySelectorAll(".term-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".term-btn").forEach(b => b.classList.remove("term-btn--active"));
    btn.classList.add("term-btn--active");
    loanTerm = parseInt(btn.dataset.years);
    update();
  });
});

// ── "What can I afford?" chat ──────────────────────────────────
const affordBtn      = document.getElementById("affordBtn");
const incomeInput    = document.getElementById("incomeInput");
const affordChat     = document.getElementById("affordChat");
const affordMessages = document.getElementById("affordMessages");
const affordTyping   = document.getElementById("affordTyping");
const affordReplyRow = document.getElementById("affordReplyRow");
const affordFollowup = document.getElementById("affordFollowup");
const affordFollowBtn = document.getElementById("affordFollowBtn");

function appendAffordMsg(role, text) {
  const div = document.createElement("div");
  div.className = `afford-msg afford-msg--${role}`;
  div.innerHTML = text
    .split(/\n\n+/)
    .filter(Boolean)
    .map(p => `<p>${p.replace(/\n/g, "<br>")}</p>`)
    .join("");
  affordMessages.appendChild(div);
  affordMessages.scrollTop = affordMessages.scrollHeight;
}

async function askAfford(income, followup) {
  if (affordWaiting) return;
  affordWaiting = true;
  affordChat.style.display    = "block";
  affordTyping.style.display  = "flex";
  affordReplyRow.style.display = "none";

  const body = income
    ? { income, history: [] }
    : { income: "", message: followup, history: chatHistory };

  try {
    const res  = await fetch("/calculator-chat", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(body),
    });
    const data = await res.json();
    affordTyping.style.display = "none";

    if (data.error) {
      appendAffordMsg("alex", `Sorry — ${data.error}`);
    } else {
      appendAffordMsg("alex", data.reply);
      chatHistory = data.history;
      affordReplyRow.style.display = "flex";
    }
  } catch {
    affordTyping.style.display = "none";
    appendAffordMsg("alex", "Couldn't reach Alex right now. Please try again.");
  } finally {
    affordWaiting = false;
  }
}

affordBtn.addEventListener("click", () => {
  const income = incomeInput.value.trim();
  if (!income) { incomeInput.focus(); return; }
  appendAffordMsg("user", `My gross monthly income is $${Number(income).toLocaleString()}.`);
  document.getElementById("affordInputRow").style.display = "none";
  askAfford(income, null);
});

incomeInput.addEventListener("keydown", e => {
  if (e.key === "Enter") affordBtn.click();
});

affordFollowBtn.addEventListener("click", () => {
  const msg = affordFollowup.value.trim();
  if (!msg) return;
  appendAffordMsg("user", msg);
  affordFollowup.value = "";
  askAfford(null, msg);
});

affordFollowup.addEventListener("keydown", e => {
  if (e.key === "Enter") affordFollowBtn.click();
});

// ── Embed code copy ────────────────────────────────────────────
const embedCopyBtn = document.getElementById("embedCopyBtn");
if (embedCopyBtn) {
  embedCopyBtn.addEventListener("click", () => {
    const code = document.getElementById("embedCode").textContent;
    navigator.clipboard.writeText(code).then(() => {
      embedCopyBtn.textContent = "Copied!";
      setTimeout(() => { embedCopyBtn.textContent = "Copy Code"; }, 2000);
    });
  });
}

// ── Slider track fill (visual) ─────────────────────────────────
function fillSlider(slider) {
  const min = parseFloat(slider.min);
  const max = parseFloat(slider.max);
  const val = parseFloat(slider.value);
  const pct = ((val - min) / (max - min)) * 100;
  slider.style.setProperty("--fill", pct + "%");
}

[homePrice, downPct, rate].forEach(slider => {
  slider.addEventListener("input", () => fillSlider(slider));
  fillSlider(slider);
});

// ── Init ───────────────────────────────────────────────────────
update();
