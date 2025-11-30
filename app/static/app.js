/**
 * app.js — global frontend logic for PickUp Livery
 *
 * Contains:
 *  - Geolocation capture for pickup page
 *  - Image preview for pickup form
 *  - Theme toggle (light/dark)
 *  - Mobile menu toggle
 *  - Admin AJAX forms (prevent full page reload)
 *  - Admin <details> state persistence (open/closed)
 *  - Prevent useless reload when clicking the same active nav item (sidebar, mobile, logo)
 */

 // ----- Geolocation (pickup page) -----
async function captureLocation() {
  if (!navigator.geolocation) {
    alert("Geolocation not supported by your browser");
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const latEl = document.getElementById("lat");
      const lonEl = document.getElementById("lon");
      const statusEl = document.getElementById("geo-status");

      if (latEl) latEl.value = pos.coords.latitude;
      if (lonEl) lonEl.value = pos.coords.longitude;
      if (statusEl) statusEl.textContent = "📍 Location captured";
    },
    (err) => {
      alert("Error getting location: " + err.message);
    }
  );
}

// ----- Preview image before upload (pickup page) -----
function previewFile(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const img = document.getElementById("preview");
    if (!img) return;
    img.src = e.target.result;
    img.style.display = "block";
  };
  reader.readAsDataURL(file);
}

// ----- Theme + Mobile menu + Admin AJAX forms + Details state -----
document.addEventListener("DOMContentLoaded", () => {
  // ----- Geolocation / file preview -----
  const geoBtn = document.getElementById("geo-btn");
  if (geoBtn) geoBtn.addEventListener("click", captureLocation);

  const fileInput = document.getElementById("image");
  if (fileInput) {
    fileInput.addEventListener("change", () => previewFile(fileInput));
  }

  // ----- THEME TOGGLE -----
  const html = document.documentElement;
  const stored = window.localStorage.getItem("theme");
  if (stored === "light" || stored === "dark") {
    html.dataset.theme = stored;
  } else {
    html.dataset.theme = html.dataset.theme || "light";
  }

  function toggleTheme() {
    const current = html.dataset.theme === "dark" ? "dark" : "light";
    const next = current === "dark" ? "light" : "dark";
    html.dataset.theme = next;
    window.localStorage.setItem("theme", next);
  }

  document.querySelectorAll("[data-toggle-theme]").forEach((btn) => {
    btn.addEventListener("click", toggleTheme);
  });

  // ----- MOBILE MENU -----
  const mobileMenu = document.getElementById("mobileMenu");

  function toggleMenu() {
    if (!mobileMenu) return;
    mobileMenu.classList.toggle("is-open");
  }

  document.querySelectorAll("[data-toggle-menu]").forEach((btn) => {
    btn.addEventListener("click", toggleMenu);
  });

  if (mobileMenu) {
    mobileMenu.addEventListener("click", (ev) => {
      if (ev.target === mobileMenu) toggleMenu();
    });
  }

  // ----- ADMIN: AJAX forms -----
  function getSubmitButton(form) {
    let btn = form.querySelector('button[type="submit"]');
    if (!btn) btn = form.querySelector("button");
    return btn;
  }

  async function handleAjaxFormSubmit(event) {
    const form = event.target;

    if (!form.classList.contains("js-ajax-form")) return;
    event.preventDefault();

    const submitBtn = getSubmitButton(form);
    const originalBtnText = submitBtn ? submitBtn.textContent : null;

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Saving…";
    }

    try {
      const formData = new FormData(form);
      const method = (form.method || "post").toUpperCase();
      const action = form.action || window.location.href;

      const response = await fetch(action, {
        method,
        body: formData,
        headers: { "X-Requested-With": "XMLHttpRequest" }
      });

      if (!response.ok) {
        console.error("Admin AJAX error:", response.status, response.statusText);
        if (submitBtn) submitBtn.textContent = "Error";
        setTimeout(() => {
          if (submitBtn && originalBtnText) {
            submitBtn.textContent = originalBtnText;
            submitBtn.disabled = false;
          }
        }, 1200);
        return;
      }

      if (submitBtn) submitBtn.textContent = "Saved ✓";

      setTimeout(() => {
        if (submitBtn && originalBtnText) {
          submitBtn.textContent = originalBtnText;
          submitBtn.disabled = false;
        }
      }, 1000);

    } catch (err) {
      console.error("Admin AJAX exception:", err);
      if (submitBtn) submitBtn.textContent = "Error";
      setTimeout(() => {
        if (submitBtn && originalBtnText) {
          submitBtn.textContent = originalBtnText;
          submitBtn.disabled = false;
        }
      }, 1200);
    }
  }

  document.addEventListener("submit", handleAjaxFormSubmit, true);

  // ----- ADMIN: remember <details> state -----
  const DETAILS_STATE_KEY = "adminDetailsState";

  function loadDetailsState() {
    try {
      const raw = window.localStorage.getItem(DETAILS_STATE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return typeof parsed === "object" && parsed !== null ? parsed : {};
    } catch {
      return {};
    }
  }

  function saveDetailsState(state) {
    try {
      window.localStorage.setItem(DETAILS_STATE_KEY, JSON.stringify(state));
    } catch {}
  }

  const detailsState = loadDetailsState();

  document.querySelectorAll("details.g-section").forEach((det, index) => {
    const id = det.dataset.sectionId || `details-${index}`;
    det.dataset.sectionId = id;

    if (detailsState[id] === true) det.open = true;
    else if (detailsState[id] === false) det.open = false;

    det.addEventListener("toggle", () => {
      detailsState[id] = det.open;
      saveDetailsState(detailsState);
    });
  });

  // ----- PREVENT RELOAD WHEN CLICKING NAV ITEM THAT ALREADY MATCHES URL -----
  // function preventReloadOnActive(selector) {
  //   document.querySelectorAll(selector).forEach((link) => {
  //     link.addEventListener("click", (ev) => {
  //       const href = link.getAttribute("href");
  //       if (!href) return;

  //       const currentPath = window.location.pathname || "/";
  //       if (href === currentPath) {
  //         // We are already on this page -> do NOT reload it again
  //         ev.preventDefault();
  //       }
  //     });
  //   });
  // }

  // // Sidebar nav icons
  // preventReloadOnActive(".sidebar-nav .sidebar-link");
  // // Mobile menu links
  // preventReloadOnActive(".mobile-menu-links .mobile-link");
  // // LOGO in sidebar (desktop)
  // preventReloadOnActive(".sidebar-logo .sidebar-brand");
  // // LOGO / brand in mobile header
  // preventReloadOnActive(".mobile-header .mobile-brand");
});
