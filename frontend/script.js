// ─── CONFIG ───────────────────────────────────────────────
const BACKEND = "http://localhost:8000"; // Change to your deployed backend URL

// ─── STATE ────────────────────────────────────────────────
let token = null;
let currentUser = null;

// ─── ON LOAD ──────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  // Check for token in URL (redirect from Discord OAuth)
  const params = new URLSearchParams(window.location.search);
  const urlToken = params.get("token");
  if (urlToken) {
    localStorage.setItem("poti_token", urlToken);
    window.history.replaceState({}, "", window.location.pathname + "#shop");
  }

  token = localStorage.getItem("poti_token");
  if (token) {
    await loadUser();
  }
});

async function loadUser() {
  try {
    const res = await fetch(`${BACKEND}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      logout();
      return;
    }
    currentUser = await res.json();
    showLoggedIn();
    await loadHistory();
  } catch (e) {
    console.error(e);
  }
}

function showLoggedIn() {
  // Nav
  document.getElementById("btn-login").classList.add("hidden");
  document.getElementById("btn-shop-nav").style.display = "block";
  const navUser = document.getElementById("nav-user");
  navUser.classList.add("visible");
  document.getElementById("nav-avatar").src =
    currentUser.avatar || "https://cdn.discordapp.com/embed/avatars/0.png";
  document.getElementById("nav-username").textContent = currentUser.username;

  // Shop
  document.getElementById("shop-login-wall").style.display = "none";
  document.getElementById("shop-content").classList.add("visible");

  // Balance
  const REALMS = [
    "",
    "Qi Condensation",
    "Foundation Building",
    "Core Formation",
    "Nascent Soul",
    "Spirit Severing",
    "Dao Seeking",
    "True Immortal",
  ];
  document.getElementById("bal-realm").textContent =
    REALMS[currentUser.realm] || "Unknown";
  document.getElementById("bal-stones").textContent =
    "🪙 " + currentUser.spirit_stones.toLocaleString();
  document.getElementById("bal-jade").textContent =
    "💎 " + currentUser.jade_coins.toLocaleString();
}

function loginWithDiscord() {
  window.location.href = `${BACKEND}/auth/login`;
}

function logout() {
  localStorage.removeItem("poti_token");
  token = null;
  currentUser = null;
  location.reload();
}

// ─── CHECKOUT ─────────────────────────────────────────────
async function checkout(packageId, btn) {
  if (!token) {
    loginWithDiscord();
    return;
  }

  const originalText = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Creating order…';

  try {
    const res = await fetch(`${BACKEND}/shop/checkout/${packageId}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    });
    if (!res.ok) {
      const err = await res.json();
      showToast("Error: " + (err.detail || "Something went wrong"), "error");
      return;
    }
    const data = await res.json();

    // Open Midtrans Snap popup
    window.snap.pay(data.snap_token, {
      onSuccess: async (result) => {
        showToast(
          "Payment successful! Jade Coins are being credited…",
          "success",
        );
        setTimeout(async () => {
          await loadUser();
          await loadHistory();
        }, 3000);
      },
      onPending: (result) => {
        showToast(
          "Waiting for BCA transfer. Complete it before it expires!",
          "success",
        );
        loadHistory();
      },
      onError: (result) => {
        showToast("Payment failed. Please try again.", "error");
      },
      onClose: () => {
        showToast("Payment window closed.", "error");
      },
    });
  } catch (e) {
    showToast("Network error. Please try again.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

// ─── HISTORY ──────────────────────────────────────────────
async function loadHistory() {
  try {
    const res = await fetch(`${BACKEND}/shop/history`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const rows = await res.json();
    if (!rows.length) return;

    document.getElementById("history-wrap").style.display = "block";
    const list = document.getElementById("history-list");
    list.innerHTML = `
        <div class="history-row">
          <span>Package</span><span>Coins</span><span>Status</span>
        </div>
      `;
    rows.forEach((r) => {
      const statusClass =
        r.status === "paid"
          ? "badge-paid"
          : r.status === "pending"
            ? "badge-pending"
            : "badge-expire";
      const date = new Date(r.created_at).toLocaleDateString("id-ID");
      list.innerHTML += `
          <div class="history-row">
            <span>${r.package_id} <span style="color:var(--mist-dim);font-size:0.75rem">${date}</span></span>
            <span style="color:var(--gold-light)">💎 ${r.jade_coins.toLocaleString()}</span>
            <span class="${statusClass}">${r.status}</span>
          </div>
        `;
    });
  } catch (e) {
    console.error(e);
  }
}

// ─── TOAST ────────────────────────────────────────────────
function showToast(msg, type = "success") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = `toast ${type} show`;
  setTimeout(() => {
    t.className = "toast";
  }, 4000);
}
