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
 *  - Admin toast alerts for errors / info / success
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

  const iconEl = document.createElement("div");
  iconEl.className = "admin-alert__icon";

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

  const actionEl = document.createElement("div");
  actionEl.className = "admin-alert__action";

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "admin-alert__close";
  closeBtn.setAttribute("aria-label", "Dismiss notification");
  closeBtn.innerHTML = '<span aria-hidden="true">✕</span>';

  closeBtn.addEventListener("click", () => {
    alertEl.classList.remove("is-visible");
    setTimeout(() => {
      if (alertEl.parentElement) {
        alertEl.parentElement.removeChild(alertEl);
      }
    }, 200);
  });

  actionEl.appendChild(closeBtn);

  alertEl.appendChild(iconEl);
  alertEl.appendChild(bodyEl);
  alertEl.appendChild(actionEl);

  container.appendChild(alertEl);

  requestAnimationFrame(() => {
    alertEl.classList.add("is-visible");
  });

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
// Helper: close all chip dropdowns
// ------------------------------------------------------
function closeAllChipDropdowns(except) {
  document
    .querySelectorAll(".chip-dropdown-wrapper.is-open")
    .forEach((w) => {
      if (w !== except) {
        w.classList.remove("is-open");
        w.classList.remove("drop-up");
      }
    });
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

  // ----------------------------------------------------
  // ADMIN: CHIP DROPDOWNS (Role, Region, Assign user, GPS mode)
  // ----------------------------------------------------
  function initChipDropdowns() {
    const wrappers = document.querySelectorAll(".chip-dropdown-wrapper");
    if (!wrappers.length) return;

    wrappers.forEach((wrapper) => {
      // Skip history page filter chips and export-format chip
      if (
        wrapper.closest("#historyFilters") ||
        wrapper.classList.contains("export-format-wrapper")
      ) {
        return;
      }

      // Prevent double initialization
      if (wrapper.dataset.chipInitialized === "1") return;
      wrapper.dataset.chipInitialized = "1";

      const button = wrapper.querySelector(".chip-dropdown");
      const menu = wrapper.querySelector(".dropdown-menu");
      const hiddenInput = wrapper.querySelector('input[type="hidden"]');
      const mainText = wrapper.querySelector(".chip-main-text");

      if (!button || !menu) return;

      button.addEventListener("click", (ev) => {
        ev.preventDefault();

        const wasOpen = wrapper.classList.contains("is-open");

        // Close all others first
        closeAllChipDropdowns(wrapper);

        // If this one was open — just close and exit
        if (wasOpen) {
          wrapper.classList.remove("is-open");
          wrapper.classList.remove("drop-up");
          return;
        }

        // --------- Measure available space and menu height ----------
        const rect = wrapper.getBoundingClientRect();
        const viewportHeight =
          window.innerHeight || document.documentElement.clientHeight || 0;

        const spaceBelow = viewportHeight - rect.bottom;
        const spaceAbove = rect.top;

        // Try to measure real dropdown height (it is "display: none" by default)
        let menuHeight = 220; // fallback
        if (menu) {
          const prevDisplay = menu.style.display;
          const prevVisibility = menu.style.visibility;

          // Temporarily show it off-screen (invisible) to get offsetHeight
          menu.style.visibility = "hidden";
          menu.style.display = "block";

          menuHeight = menu.offsetHeight || menuHeight;

          // Restore previous inline styles
          menu.style.display = prevDisplay;
          menu.style.visibility = prevVisibility;
        }

        
        if (spaceBelow < menuHeight + 8 && spaceAbove > spaceBelow) {
          wrapper.classList.add("drop-up");
        } else {
          wrapper.classList.remove("drop-up");
        }

        // Finally open
        wrapper.classList.add("is-open");
      });

      menu.querySelectorAll(".dropdown-item").forEach((item) => {
        item.addEventListener("click", (ev) => {
          ev.preventDefault();
          const value = item.dataset.value || "";
          const label = item.textContent.trim();

          menu.querySelectorAll(".dropdown-item").forEach((i) => {
            i.classList.toggle("is-active", i === item);
          });

          if (mainText && label) {
            mainText.textContent = label;
          }

          if (hiddenInput && value) {
            hiddenInput.value = value;
          }

          wrapper.classList.remove("is-open");
        });
      });
    });
  }

  initChipDropdowns();

  // ----------------------------------------------------
  // ADMIN: cutoff modal open / close
  // ----------------------------------------------------
  function openCutoffModal(pharmacyId) {
    const selector = `.cutoff-modal-backdrop[data-cutoff-modal="${pharmacyId}"]`;
    const backdrop = document.querySelector(selector);
    if (!backdrop) return;
    backdrop.hidden = false;
    document.body.classList.add("modal-open");
  }

  function closeCutoffModal(backdrop) {
    if (!backdrop) return;
    backdrop.hidden = true;
    document.body.classList.remove("modal-open");
  }

  document.querySelectorAll(".js-open-cutoff-modal").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.pharmacyId;
      if (!id) return;
      openCutoffModal(id);
    });
  });

  document.querySelectorAll(".cutoff-modal-backdrop").forEach((backdrop) => {
    backdrop.addEventListener("click", (ev) => {
      if (ev.target === backdrop) {
        closeCutoffModal(backdrop);
      }
    });

    const closeBtn = backdrop.querySelector(".js-close-cutoff-modal");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => closeCutoffModal(backdrop));
    }
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      document
        .querySelectorAll(".cutoff-modal-backdrop:not([hidden])")
        .forEach((backdrop) => {
          closeCutoffModal(backdrop);
        });
    }
  });

  // ----------------------------------------------------
  // ADMIN: helper for weekday cutoffs UI (Mon–Fri)
  // ----------------------------------------------------
  document.querySelectorAll(".pharmacy-cutoffs-form").forEach((form) => {
    const applyBtn = form.querySelector(".js-apply-weekdays");
    const weekdaysInput = form.querySelector('input[name="weekdays_time"]');

    if (!applyBtn || !weekdaysInput) return;

    applyBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      const value = weekdaysInput.value || "";
      if (!value) {
        showAdminAlert("Set Mon–Fri time first before applying.", "info");
        return;
      }

      const days = ["mon", "tue", "wed", "thu", "fri"];
      days.forEach((name) => {
        const inp = form.querySelector(`input[name="${name}"]`);
        if (inp) {
          inp.value = value;
        }
      });

      showAdminAlert("Applied Mon–Fri time to Mon–Fri fields.", "success");
    });
  });

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

    // -----------------------------
    // 0) CREATE: user / region / pharmacy
    // -----------------------------

    // 0.1. Create user
    if (actionType === "user-create") {
      if (!data || !data.ok || !data.user) {
        showAdminAlert("User was not created. Invalid response.", "error");
        return;
      }

      const u = data.user;
      const roleLabel =
        u.role === "admin"
          ? "Admin"
          : u.role === "driver"
            ? "Driver"
            : u.role === "history"
              ? "History only"
              : u.role;

      const gpsMode = u.gps_mode || "inherit";

      const usersSection = document.querySelector(
        'details.g-section[data-section-id="admin-users"]'
      );
      if (!usersSection) return;
      const tbody = usersSection.querySelector("table tbody");
      if (!tbody) return;

      const row = document.createElement("tr");
      row.dataset.userId = u.id;

      row.innerHTML = `
        <td>${u.id}</td>
        <td>${u.login}</td>
        <td>${roleLabel}</td>

        <td>
          ${u.is_active
          ? '<span class="status-pill status-ok">Yes</span>'
          : '<span class="status-pill">No</span>'
        }
        </td>

        <td>
          <div class="user-gps-block">
            <form
              action="/admin/users/${u.id}/gps"
              method="post"
              class="gps-inline-form js-ajax-form"
              data-admin-action="user-gps-update"
            >
              <div class="chip-dropdown-wrapper gps-mode-wrapper">
                <button type="button" class="chip chip-dropdown chip-gps">
                  <span class="chip-main-text">
                    ${gpsMode === "inherit"
          ? "Inherit global"
          : gpsMode === "require"
            ? "Require GPS"
            : "GPS not required"
        }
                  </span>
                  <span class="chip-caret"></span>
                </button>

                <div class="dropdown-menu">
                  <button type="button"
                          class="dropdown-item ${gpsMode === "inherit" ? "is-active" : ""
        }"
                          data-value="inherit">
                    Inherit global
                  </button>
                  <button type="button"
                          class="dropdown-item ${gpsMode === "require" ? "is-active" : ""
        }"
                          data-value="require">
                    Require GPS
                  </button>
                  <button type="button"
                          class="dropdown-item ${gpsMode === "no" ? "is-active" : ""
        }"
                          data-value="no">
                    GPS not required
                  </button>
                </div>

                <input type="hidden" name="gps_mode" value="${gpsMode}">
              </div>

              <button type="submit" class="btn btn-secondary btn-sm-inline">Update</button>
            </form>
          </div>
        </td>

        <td>
          <div class="form-actions form-actions-row">

            <form
              action="/admin/users/${u.id}/password"
              method="post"
              class="form-grid js-ajax-form"
              data-admin-action="user-password-change"
            >
              <input type="password" name="new_password" placeholder="new password" minlength="6" required class="form-input">
              <button type="submit" class="btn btn-primary">Set</button>
            </form>

            <form
              action="/admin/users/${u.id}/toggle-active"
              method="post"
              class="js-ajax-form"
              data-admin-action="user-toggle-active"
            >
              <button type="submit" class="btn btn-secondary btn-toggle">
                ${u.is_active ? "Deactivate" : "Activate"}
              </button>
            </form>

            <hr class="newdevider" />

            <form
              action="/admin/users/${u.id}/delete"
              method="post"
              class="js-ajax-form"
              data-admin-action="user-delete"
              onsubmit="return confirm('Delete user ${u.login}? This cannot be undone.');"
            >
              <button type="submit" class="btn btn-primary btn-danger">Delete</button>
            </form>

          </div>
        </td>
      `;

      tbody.appendChild(row);

      // Add new user to "Assign user" dropdowns for all pharmacies,
      // but only if role is NOT "history".
      // Admins and drivers can be assigned; history users are excluded.
      if (u.role !== "history") {
        const assignWrappers = document.querySelectorAll(".assign-user-wrapper");
        assignWrappers.forEach((wrapper) => {
          const menu = wrapper.querySelector(".dropdown-menu");
          const mainText = wrapper.querySelector(".chip-main-text");
          const hiddenInput = wrapper.querySelector('input[name="user_id"]');
          if (!menu) return;

          // Check if this user is already in this menu
          const exists = menu.querySelector(
            `.dropdown-item[data-value="${u.id}"]`
          );
          if (exists) return;

          const itemsBefore = menu.querySelectorAll(".dropdown-item").length;

          const btn = document.createElement("button");
          btn.type = "button";
          btn.className =
            "dropdown-item" + (itemsBefore === 0 ? " is-active" : "");
          btn.dataset.value = u.id;
          btn.textContent = u.login;
          menu.appendChild(btn);

          // If this was the first user in the menu, make them default selection
          if (itemsBefore === 0) {
            if (mainText) mainText.textContent = u.login;
            if (hiddenInput) hiddenInput.value = u.id;
          }
        });
      }

      // Re-initialize dropdowns (new row + new menu items)
      initChipDropdowns();

      form.reset();
      showAdminAlert(`User "${u.login}" created`, "success");
      return;
    }

    // 0.2. Create region
    if (actionType === "region-create") {
      if (!data || !data.ok || !data.region) {
        showAdminAlert("Region was not created. Invalid response.", "error");
        return;
      }

      const r = data.region;

      const regionsSection = document.querySelector(
        'details.g-section[data-section-id="admin-regions"]'
      );
      if (!regionsSection) return;
      const tbody = regionsSection.querySelector("table tbody");
      if (!tbody) return;

      const row = document.createElement("tr");
      row.dataset.regionId = r.id;

      row.innerHTML = `
        <td>${r.id}</td>
        <td>${r.name}</td>
        <td>
          ${r.is_active
          ? '<span class="status-pill status-ok">Yes</span>'
          : '<span class="status-pill">No</span>'
        }
        </td>
        <td>
          <div class="form-actions form-actions-row">
            <form
              action="/admin/regions/${r.id}/toggle"
              method="post"
              class="js-ajax-form"
              data-admin-action="region-toggle-active"
            >
              <button type="submit" class="btn btn-secondary btn-toggle">
                ${r.is_active ? "Deactivate" : "Activate"}
              </button>
            </form>

            <hr class="newdevider" />

            <form
              action="/admin/regions/${r.id}/delete"
              method="post"
              class="js-ajax-form"
              data-admin-action="region-delete"
              onsubmit="return confirm('Delete region ${r.name}? This cannot be undone.');"
            >
              <button type="submit" class="btn btn-primary btn-danger">Delete</button>
            </form>
          </div>
        </td>
      `;

      tbody.appendChild(row);
      form.reset();
      showAdminAlert(`Region "${r.name}" created`, "success");
      return;
    }

    // 0.3. Create pharmacy
    if (actionType === "pharmacy-create") {
      if (!data || !data.ok || !data.pharmacy) {
        showAdminAlert("Pharmacy was not created. Invalid response.", "error");
        return;
      }

      const ph = data.pharmacy;
      showAdminAlert(`Pharmacy "${ph.name}" created`, "success");

      // Row with all columns is complex; easiest is to reload the page
      setTimeout(() => {
        window.location.reload();
      }, 500);

      return;
    }

    // -----------------------------
    // 1) Toggle active user / region / pharmacy
    // -----------------------------

    if (actionType === "user-toggle-active") {
      const row = form.closest("tr");
      if (!row) return;

      const btn = getSubmitButton(form);
      const isActive = flipStatusPill(row);

      if (btn && isActive !== null) {
        btn.textContent = isActive ? "Deactivate" : "Activate";
      }

      if (isActive !== null) {
        const loginCell =
          row.cells && row.cells[1] ? row.cells[1].textContent.trim() : "";
        const msg = isActive
          ? `User "${loginCell}" activated`
          : `User "${loginCell}" deactivated`;
        showAdminAlert(msg, "success");
      }
      return;
    }

    if (actionType === "region-toggle-active") {
      const row = form.closest("tr");
      if (!row) return;

      const btn = getSubmitButton(form);
      const isActive = flipStatusPill(row);

      if (btn && isActive !== null) {
        btn.textContent = isActive ? "Deactivate" : "Activate";
      }

      if (isActive !== null) {
        const nameCell =
          row.cells && row.cells[1] ? row.cells[1].textContent.trim() : "";
        const msg = isActive
          ? `Region "${nameCell}" activated`
          : `Region "${nameCell}" deactivated`;
        showAdminAlert(msg, "success");
      }
      return;
    }

    if (actionType === "pharmacy-toggle-active") {
      const row = form.closest("tr");
      if (!row) return;

      const btn = getSubmitButton(form);
      const isActive = flipStatusPill(row);

      if (btn && isActive !== null) {
        btn.textContent = isActive ? "Deactivate" : "Activate";
      }

      if (isActive !== null) {
        const nameCell =
          row.cells && row.cells[1] ? row.cells[1].textContent.trim() : "";
        const msg = isActive
          ? `Pharmacy "${nameCell}" activated`
          : `Pharmacy "${nameCell}" deactivated`;
        showAdminAlert(msg, "success");
      }
      return;
    }

    // -----------------------------
    // 2) Assign / unassign user
    // -----------------------------

    if (actionType === "pharmacy-assign-user") {
      if (data && data.already_assigned) {
        showAdminAlert("User is already assigned to this pharmacy.", "info");
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
      const userName = assignChip ? assignChip.textContent.trim() : "User";

      const existingChip = chipsContainer.querySelector(
        'form.assigned-chip input[name="user_id"][value="' + userId + '"]'
      );
      if (existingChip) {
        showAdminAlert("User is already assigned to this pharmacy.", "info");
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

      showAdminAlert(`User "${userName}" assigned`, "success");
      return;
    }

    if (actionType === "pharmacy-unassign-user") {
      const chipForm = form.closest(".assigned-chip") || form;
      let userName = "";
      if (chipForm) {
        const nameSpan = chipForm.querySelector(".assigned-name");
        if (nameSpan) userName = nameSpan.textContent.trim();
      }

      if (chipForm && chipForm.parentElement) {
        chipForm.parentElement.removeChild(chipForm);
      }

      if (userName) {
        showAdminAlert(`User "${userName}" unassigned`, "success");
      } else {
        showAdminAlert("User unassigned", "success");
      }
      return;
    }

    // -----------------------------
    // 3) Delete user / region / pharmacy
    // -----------------------------
    if (
      actionType === "user-delete" ||
      actionType === "region-delete" ||
      actionType === "pharmacy-delete"
    ) {
      const row = form.closest("tr");
      let label = "";
      let deletedUserId = null;

      if (row) {
        // Column[1] usually holds login / region name / pharmacy name
        if (row.cells && row.cells[1]) {
          label = row.cells[1].textContent.trim();
        }

        // For users we also try to read the user id from data-attribute or first cell
        if (actionType === "user-delete") {
          // Prefer data-user-id set when creating user via JS
          deletedUserId = row.dataset.userId || null;

          // Fallback: take first cell text (ID column)
          if (!deletedUserId && row.cells && row.cells[0]) {
            deletedUserId = row.cells[0].textContent.trim();
          }
        }

        if (row.parentElement) {
          row.parentElement.removeChild(row);
        }
      }

      // Extra logic ONLY for user-delete:
      // remove this user from all "Assign user" dropdown menus
      if (actionType === "user-delete" && deletedUserId) {
        document.querySelectorAll(".assign-user-wrapper").forEach((wrapper) => {
          const menu = wrapper.querySelector(".dropdown-menu");
          if (!menu) return;

          const item = menu.querySelector(
            `.dropdown-item[data-value="${deletedUserId}"]`
          );
          if (!item) return;

          const wasActive = item.classList.contains("is-active");
          const mainText = wrapper.querySelector(".chip-main-text");
          const hiddenInput = wrapper.querySelector('input[name="user_id"]');

          // Remove the deleted user option from the menu
          item.remove();

          // If the removed option was currently selected,
          // pick a new default (first item) or clear the selection
          if (wasActive) {
            const remainingItems = menu.querySelectorAll(".dropdown-item");

            if (remainingItems.length > 0) {
              const first = remainingItems[0];

              remainingItems.forEach((btn, idx) => {
                btn.classList.toggle("is-active", idx === 0);
              });

              if (mainText) {
                mainText.textContent = first.textContent.trim();
              }
              if (hiddenInput) {
                hiddenInput.value = first.dataset.value || "";
              }
            } else {
              // No users left in menu → clear label and hidden value
              if (mainText) {
                mainText.textContent = "Select user";
              }
              if (hiddenInput) {
                hiddenInput.value = "";
              }
            }
          }
        });
      }

      let msg = "Item deleted.";
      if (actionType === "user-delete") {
        msg = label ? `User "${label}" deleted.` : "User deleted.";
      } else if (actionType === "region-delete") {
        msg = label ? `Region "${label}" deleted.` : "Region deleted.";
      } else if (actionType === "pharmacy-delete") {
        msg = label ? `Pharmacy "${label}" deleted.` : "Pharmacy deleted.";
      }

      showAdminAlert(msg, "success");
      return;
    }


    // -----------------------------
    // 4) Other: GPS / password / cutoffs
    // -----------------------------

    if (actionType === "user-gps-update") {
      showAdminAlert("GPS setting updated", "success");
      return;
    }

    if (actionType === "user-password-change") {
      const pwdInput = form.querySelector('input[name="new_password"]');
      if (pwdInput) pwdInput.value = "";
      showAdminAlert("Password updated", "success");
      return;
    }

    if (actionType === "pharmacy-cutoff-update") {
      const block = form.closest(".pharmacy-cutoff-block");
      if (!block) {
        showAdminAlert("Cutoff updated, but UI block not found.", "info");
        return;
      }

      const currentNode = block.querySelector(".pharmacy-cutoff-current");
      if (!currentNode) {
        showAdminAlert("Cutoff updated, but label container missing.", "info");
        return;
      }

      const timeInput = form.querySelector(
        'input[name="latest_pickup_time_local"]'
      );
      if (timeInput) {
        timeInput.value = "";
      }

      let utcLabel = null;
      let hasCutoff = true;

      if (data) {
        if (typeof data.latest_pickup_time_utc_label === "string") {
          utcLabel = data.latest_pickup_time_utc_label.trim();
        } else if (typeof data.latest_pickup_time_utc === "string") {
          const raw = data.latest_pickup_time_utc.trim();

          if (/^\d{2}:\d{2}(:\d{2})?$/.test(raw)) {
            utcLabel = raw.slice(0, 5);
          } else if (raw.length >= 16) {
            utcLabel = raw.slice(11, 16);
          } else {
            utcLabel = raw;
          }
        } else if (data.latest_pickup_time_utc === null) {
          hasCutoff = false;
        }

        if (data.has_cutoff === false) {
          hasCutoff = false;
        }
      }

      let pill = currentNode.querySelector(".status-pill");
      let muted = currentNode.querySelector(".muted");

      if (!hasCutoff) {
        if (pill && pill.parentElement) {
          pill.parentElement.removeChild(pill);
        }
        if (!muted) {
          muted = document.createElement("span");
          muted.className = "muted";
          currentNode.innerHTML = "";
          currentNode.appendChild(muted);
        }
        muted.textContent = "No cutoff";
      } else if (utcLabel) {
        const labelText = `${utcLabel} UTC`;

        if (!pill) {
          pill = document.createElement("span");
          pill.className = "status-pill status-ok";
          currentNode.innerHTML = "";
          currentNode.appendChild(pill);
        } else {
          pill.classList.add("status-ok");
        }
        pill.textContent = labelText;

        if (muted && muted.parentElement) {
          muted.parentElement.removeChild(muted);
        }
      }

      showAdminAlert("Cutoff time updated", "success");
      return;
    }

    if (actionType === "pharmacy-cutoffs-update") {
      const row = form.closest("tr");
      if (row) {
        const summaryText = row.querySelector(".pharmacy-cutoff-summary-text");
        if (summaryText) {
          const days = [
            { name: "mon", label: "Mon" },
            { name: "tue", label: "Tue" },
            { name: "wed", label: "Wed" },
            { name: "thu", label: "Thu" },
            { name: "fri", label: "Fri" },
            { name: "sat", label: "Sat" },
            { name: "sun", label: "Sun" },
          ];

          const parts = days.map((d) => {
            const inp = form.querySelector(`input[name="${d.name}"]`);
            const val = inp && inp.value ? inp.value : "—";
            return `${d.label} ${val || "—"}`;
          });

          summaryText.textContent = parts.join(", ");
        }
      }

      const backdrop = form.closest(".cutoff-modal-backdrop");
      if (backdrop) {
        backdrop.hidden = true;
      }
      document.body.classList.remove("modal-open");

      showAdminAlert("Weekly cutoff times updated", "success");
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
          try {
            const text = await response.text();
            console.log("Admin error text:", text);
          } catch {
            // ignore
          }
        }

        showAdminAlert(errorMessage, "error");

        if (submitBtn) {
          submitBtn.textContent = originalBtnText || "Error";
          submitBtn.disabled = false;
        }
        return;
      }

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

      if (hasAdminAction) {
        if (submitBtn) {
          submitBtn.disabled = false;
          if (!submitBtn.textContent && originalBtnText) {
            submitBtn.textContent = originalBtnText;
          }
        }
        return;
      }

      if (submitBtn) submitBtn.textContent = "Saved";

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

  // ----------------------------------------------------
  // Global close for chip dropdowns (attach ONCE)
  // ----------------------------------------------------
  document.addEventListener("click", (ev) => {
    const target = ev.target;
    if (!(target instanceof Element)) return;

    const wrapper = target.closest(".chip-dropdown-wrapper");
    if (!wrapper) {
      closeAllChipDropdowns(null);
    }
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      closeAllChipDropdowns(null);
    }
  });
});

// Optional: prevent reload on active nav item (kept commented)
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
