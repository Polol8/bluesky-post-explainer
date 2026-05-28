// Served by nginx (Docker) → use the proxied /api path (port-agnostic).
// Opened as a local file → call the backend on BACKEND_PORT directly.
const API_BASE = window.location.protocol === "file:"
  ? "http://localhost:8000"
  : "/api";

const form = document.getElementById("explain-form");
const urlInput = document.getElementById("post-url");
const submitBtn = document.getElementById("submit-btn");
const loadingEl = document.getElementById("loading");
const errorSection = document.getElementById("error-section");
const errorMsg = document.getElementById("error-msg");
const resultsEl = document.getElementById("results");

async function initProviders() {
  try {
    const resp = await fetch(`${API_BASE}/providers`);
    if (!resp.ok) return;
    const data = await resp.json();

    // Update Ollama badge with the actual model name
    if (data.ollama_model) {
      const badge = document.getElementById("ollama-badge");
      if (badge) badge.textContent = `${data.ollama_model} + DDG`;
    }

    const availability = {
      openai: data.openai,
      anthropic: data.anthropic,
      ollama: data.ollama,
    };

    for (const [provider, enabled] of Object.entries(availability)) {
      const radio = document.querySelector(`input[name="provider"][value="${provider}"]`);
      if (!radio) continue;
      const label = radio.closest("label");

      if (!enabled) {
        radio.disabled = true;
        label.classList.add("provider-disabled");
        label.title = provider === "ollama"
          ? "Ollama not running or model not pulled"
          : `${provider} API key not configured`;
        if (radio.checked) radio.checked = false;
      }
    }

    // Ensure a valid provider is always selected
    const firstEnabled = document.querySelector('input[name="provider"]:not([disabled])');
    if (firstEnabled && !document.querySelector('input[name="provider"]:checked')) {
      firstEnabled.checked = true;
    }
  } catch {
    // Backend not reachable yet — leave radios as-is
  }
}

initProviders();

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  const provider = document.querySelector('input[name="provider"]:checked').value;
  await runExplain(url, provider);
});

async function runExplain(url, provider) {
  setLoading(true);
  hideAll();

  try {
    const resp = await fetch(`${API_BASE}/explain`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, provider }),
    });

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail || `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    renderResults(data);
  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
  }
}

function renderResults(data) {
  const { post, bullets, citations, provider } = data;

  document.getElementById("res-display-name").textContent = post.author_display_name;
  document.getElementById("res-handle").textContent = `@${post.author_handle}`;
  document.getElementById("res-text").textContent = post.text;
  document.getElementById("res-likes").textContent = `♡ ${post.likes.toLocaleString()}`;
  document.getElementById("res-reposts").textContent = `↺ ${post.reposts.toLocaleString()}`;
  document.getElementById("res-replies").textContent = `💬 ${post.replies.toLocaleString()}`;
  document.getElementById("res-provider").textContent = provider;

  // Images
  const imagesEl = document.getElementById("res-images");
  imagesEl.innerHTML = "";
  for (const img of post.images || []) {
    const el = document.createElement("img");
    el.src = img.url;
    el.alt = img.alt || "Post image";
    el.loading = "lazy";
    imagesEl.appendChild(el);
  }

  // External embed
  const extEl = document.getElementById("res-external");
  if (post.external) {
    document.getElementById("res-ext-link").href = post.external.uri;
    document.getElementById("res-ext-title").textContent = post.external.title;
    document.getElementById("res-ext-desc").textContent = post.external.description;
    extEl.classList.remove("hidden");
  } else {
    extEl.classList.add("hidden");
  }

  // Bullets
  const bulletsEl = document.getElementById("res-bullets");
  bulletsEl.innerHTML = "";
  for (const b of bullets) {
    const li = document.createElement("li");
    li.textContent = b;
    bulletsEl.appendChild(li);
  }

  // Citations
  const citationsSection = document.getElementById("citations-section");
  const citationsEl = document.getElementById("res-citations");
  citationsEl.innerHTML = "";
  if (citations && citations.length > 0) {
    for (const c of citations) {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = c.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = c.title || c.url;
      a.title = c.url;
      li.appendChild(a);
      citationsEl.appendChild(li);
    }
    citationsSection.classList.remove("hidden");
  } else {
    citationsSection.classList.add("hidden");
  }

  resultsEl.classList.remove("hidden");
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorSection.classList.remove("hidden");
}

function hideAll() {
  resultsEl.classList.add("hidden");
  errorSection.classList.add("hidden");
}

function setLoading(on) {
  loadingEl.classList.toggle("hidden", !on);
  submitBtn.disabled = on;
  submitBtn.textContent = on ? "Loading…" : "Explain";
}
