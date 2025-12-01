/**
 * app.js — global frontend logic for PickUp Livery
 *
 * Contains:
 *  - Geolocation capture for pickup page
 *  - Image preview for pickup form
 *  - Theme toggle (light/dark)
 *  - Mobile menu toggle
 *  - Admin AJAX forms (prevent full page reload + live DOM updates)
 *  - Admin <details> state persistence (open/closed)
 *  - Admin toast alerts for errors
 */

// ------------------------------------------------------
// Geolocation (pickup page)
// ------------------------------------------------------
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

// ------------------------------------------------------
// Preview image before upload (pickup page)
// ------------------------------------------------------
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

// ------------------------------------------------------
// Admin toast alerts
// ------------------------------------------------------
// ------------------------------------------------------
// Admin toast alerts
// ------------------------------------------------------
function showAdminAlert(message, type = "error") {
  // type: "error" | "success" | "info"
  const containerId = "admin-alert-container";
  let container = document.getElementById(containerId);

  if (!container) {
    container = document.createElement("div");
    container.id = containerId;
    document.body.appendChild(container);
  }

  const titles = {
    error: "Error",
    success: "Success",
    info: "Notice",
  };

  const normalizedType =
    type === "success" || type === "info" || type === "error"
      ? type
      : "info";

  const alertEl = document.createElement("div");
  alertEl.className = `admin-alert admin-alert-${normalizedType}`;
  alertEl.setAttribute("role", "alert");
  alertEl.setAttribute("aria-live", "assertive");
  alertEl.setAttribute("aria-atomic", "true");

  // Icon
  const iconEl = document.createElement("div");
  iconEl.className = "admin-alert__icon";

  // Body
  const bodyEl = document.createElement("div");
  bodyEl.className = "admin-alert__body";

  const headerEl = document.createElement("h2");
  headerEl.className = "admin-alert__header";
  headerEl.textContent = titles[normalizedType] || "Notice";

  const textEl = document.createElement("p");
  textEl.className = "admin-alert__text";
  textEl.textContent = message;

  bodyEl.appendChild(headerEl);
  bodyEl.appendChild(textEl);

  // Close button
  const actionEl = document.createElement("div");
  actionEl.className = "admin-alert__action";

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "admin-alert__close";
  closeBtn.setAttribute("aria-label", "Dismiss notification");
  closeBtn.innerHTML = '<span aria-hidden="true">✕</span>';

  // Manual dismiss
  closeBtn.addEventListener("click", () => {
    alertEl.classList.remove("is-visible");
    setTimeout(() => {
      if (alertEl.parentElement) {
        alertEl.parentElement.removeChild(alertEl);
      }
    }, 200);
  });

  actionEl.appendChild(closeBtn);

  // Assemble
  alertEl.appendChild(iconEl);
  alertEl.appendChild(bodyEl);
  alertEl.appendChild(actionEl);

  container.appendChild(alertEl);

  // Fade / slide in
  requestAnimationFrame(() => {
    alertEl.classList.add("is-visible");
  });

  // Auto-hide after 4s (matches CSS countdown animation)
  setTimeout(() => {
    alertEl.classList.remove("is-visible");
    setTimeout(() => {
      if (alertEl.parentElement) {
        alertEl.parentElement.removeChild(alertEl);
      }
    }, 220);
  }, 4000);
}


// ------------------------------------------------------
// DOMContentLoaded: init everything
// ------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  // ----- Geolocation / file preview on pickup page -----
  const geoBtn = document.getElementById("geo-btn");
  if (geoBtn) geoBtn.addEventListener("click", captureLocation);

  const fileInput = document.getElementById("image");
  if (fileInput) {
    fileInput.addEventListener("change", () => previewFile(fileInput));
  }

  // ----------------------------------------------------
  // THEME TOGGLE (light / dark)
  // ----------------------------------------------------
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

  // ----------------------------------------------------
  // MOBILE MENU
  // ----------------------------------------------------
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

  // ====================================================
  // ADMIN: AJAX forms + LIVE DOM UPDATES
  // ====================================================

  function getSubmitButton(form) {
    let btn = form.querySelector('button[type="submit"]');
    if (!btn) btn = form.querySelector("button");
    return btn;
  }

  function applyAdminDomUpdate(form, actionUrl, data) {
    const actionType = form.dataset.adminAction || "";
    if (!actionType) return;

    function flipStatusPill(row) {
      const pill = row.querySelector(".status-pill");
      if (!pill) return null;

      let isActive = null;

      if (data && typeof data.is_active === "boolean") {
        isActive = data.is_active;
      } else {
        const currentlyActive =
          pill.classList.contains("status-ok") ||
          pill.textContent.trim().toLowerCase() === "yes";
        isActive = !currentlyActive;
      }

      pill.textContent = isActive ? "Yes" : "No";
      pill.classList.toggle("status-ok", isActive);

      return isActive;
    }

    // 1) Toggle user active
    if (actionType === "user-toggle-active") {
      const row = form.closest("tr");
      if (!row) return;

      const btn = getSubmitButton(form);
      const isActive = flipStatusPill(row);

      if (btn && isActive !== null) {
        btn.textContent = isActive ? "Deactivate" : "Activate";
      }
      return;
    }

    // 2) Toggle region active (update pill and button text)
    if (actionType === "region-toggle-active") {
      const row = form.closest("tr");
      if (!row) return;

      const btn = getSubmitButton(form);
      const isActive = flipStatusPill(row);

      if (btn && isActive !== null) {
        btn.textContent = isActive ? "Deactivate" : "Activate";
      }
      return;
    }

    // 3) Toggle pharmacy active (also pill + button)
    if (actionType === "pharmacy-toggle-active") {
      const row = form.closest("tr");
      if (!row) return;

      const btn = getSubmitButton(form);
      const isActive = flipStatusPill(row);

      if (btn && isActive !== null) {
        btn.textContent = isActive ? "Deactivate" : "Activate";
      }
      return;
    }

    // 4) Assign user to pharmacy
    if (actionType === "pharmacy-assign-user") {
      if (data && data.already_assigned) {
        return;
      }

      const block = form.closest(".assigned-users-block");
      if (!block) return;

      const chipsContainer = block.querySelector(".assigned-chips");
      if (!chipsContainer) return;

      const userIdInput = form.querySelector('input[name="user_id"]');
      const userId = userIdInput ? userIdInput.value : "";
      if (!userId) return;

      const assignChip = form.querySelector(".chip-main-text");
      const userName = assignChip
        ? assignChip.textContent.trim()
        : "User";

      const existingChip = chipsContainer.querySelector(
        'form.assigned-chip input[name="user_id"][value="' + userId + '"]'
      );
      if (existingChip) {
        return;
      }

      let unassignAction = form.action;
      try {
        const u = new URL(form.action, window.location.origin);
        unassignAction = u.pathname.replace(/\/assign$/, "/unassign");
      } catch {
        unassignAction = form.action.replace(/\/assign$/, "/unassign");
      }

      const chipForm = document.createElement("form");
      chipForm.action = unassignAction;
      chipForm.method = "post";
      chipForm.className = "assigned-chip js-ajax-form";
      chipForm.dataset.adminAction = "pharmacy-unassign-user";

      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "user_id";
      hidden.value = userId;

      const spanName = document.createElement("span");
      spanName.className = "assigned-name";
      spanName.textContent = userName;

      const btnRemove = document.createElement("button");
      btnRemove.type = "submit";
      btnRemove.className = "assigned-remove";
      btnRemove.title = "Unassign";
      btnRemove.textContent = "×";

      chipForm.appendChild(hidden);
      chipForm.appendChild(spanName);
      chipForm.appendChild(btnRemove);

      chipsContainer.appendChild(chipForm);
      return;
    }

    // 5) Unassign user from pharmacy
    if (actionType === "pharmacy-unassign-user") {
      const chipForm = form.closest(".assigned-chip") || form;
      if (chipForm && chipForm.parentElement) {
        chipForm.parentElement.removeChild(chipForm);
      }
      return;
    }

    // 6) Delete user / region / pharmacy -> remove table row
    if (
      actionType === "user-delete" ||
      actionType === "region-delete" ||
      actionType === "pharmacy-delete"
    ) {
      const row = form.closest("tr");
      if (row && row.parentElement) {
        row.parentElement.removeChild(row);
      }
      return;
    }

    // 7) GPS mode update → show success toast
if (actionType === "user-gps-update") {
  showAdminAlert("GPS setting updated ✓", "success");
  return;
}

  }

  async function handleAjaxFormSubmit(event) {
    const form = event.target;

    if (!form.classList.contains("js-ajax-form")) return;
    event.preventDefault();

    const submitBtn = getSubmitButton(form);
    const originalBtnText = submitBtn ? submitBtn.textContent : null;
    const hasAdminAction = !!form.dataset.adminAction;

    if (submitBtn) {
      submitBtn.disabled = true;
      if (!hasAdminAction) {
        submitBtn.textContent = "Saving…";
      }
    }

    try {
      const formData = new FormData(form);
      const method = (form.method || "post").toUpperCase();
      const action = form.action || window.location.href;

      const response = await fetch(action, {
        method,
        body: formData,
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });

      // ----- HTTP error (4xx / 5xx) -----
      if (!response.ok) {
        console.error("Admin AJAX error:", response.status, response.statusText);

        let errorMessage = `Admin error (${response.status})`;
        const ctErr = response.headers.get("content-type") || "";

        if (ctErr.includes("application/json")) {
          try {
            const errData = await response.json();
            console.log("Admin error payload:", errData);
            if (errData) {
              if (typeof errData.detail === "string") {
                errorMessage = errData.detail;
              } else if (typeof errData.error === "string") {
                errorMessage = errData.error;
              }
            }
          } catch (e) {
            console.warn("Failed to parse JSON error", e);
          }
        } else {
          // try to read plain text (e.g. HTML error)
          try {
            const text = await response.text();
            console.log("Admin error text:", text);
          } catch {}
        }

        showAdminAlert(errorMessage, "error");

        if (submitBtn) {
          submitBtn.textContent = originalBtnText || "Error";
          submitBtn.disabled = false;
        }
        return;
      }

      // Successful response
      let data = null;
      const ct = response.headers.get("content-type") || "";
      if (ct.includes("application/json")) {
        try {
          data = await response.json();
          console.log("Admin success payload:", data);
        } catch (e) {
          console.warn("Failed to parse JSON success", e);
        }
      }

      if (data && typeof data.error === "string") {
        showAdminAlert(data.error, "error");
      }

      applyAdminDomUpdate(form, action, data);

      // For admin-action forms: only re-enable the button, the label is already updated
      if (hasAdminAction) {
        if (submitBtn) {
          submitBtn.disabled = false;
        }
        return;
      }

      // Generic AJAX: “Saved ✓” -> revert label back
      if (submitBtn) submitBtn.textContent = "Saved ✓";

      setTimeout(() => {
        if (submitBtn && originalBtnText) {
          submitBtn.textContent = originalBtnText;
          submitBtn.disabled = false;
        }
      }, 1000);
    } catch (err) {
      console.error("Admin AJAX exception:", err);
      showAdminAlert("Unexpected admin error. Check console.", "error");

      if (submitBtn) {
        submitBtn.textContent = originalBtnText || "Error";
        submitBtn.disabled = false;
      }
    }
  }

  document.addEventListener("submit", handleAjaxFormSubmit, true);

  // ----------------------------------------------------
  // ADMIN: remember <details> open/closed state
  // ----------------------------------------------------
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
    } catch {
      // ignore
    }
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

  // (optional) prevent reload on active nav item — left commented out

  // ----------------------------------------------------
  // OPTIONAL: prevent reload when clicking active nav item
  // (kept commented for now)
  // ----------------------------------------------------
  // function preventReloadOnActive(selector) {
  //   document.querySelectorAll(selector).forEach((link) => {
  //     link.addEventListener("click", (ev) => {
  //       const href = link.getAttribute("href");
  //       if (!href) return;
  //
  //       const currentPath = window.location.pathname || "/";
  //       if (href === currentPath) {
  //         ev.preventDefault();
  //       }
  //     });
  //   });
  // }
  //
  // preventReloadOnActive(".sidebar-nav .sidebar-link");
  // preventReloadOnActive(".mobile-menu-links .mobile-link");
  // preventReloadOnActive(".sidebar-logo .sidebar-brand");
  // preventReloadOnActive(".mobile-header .mobile-brand");
});
