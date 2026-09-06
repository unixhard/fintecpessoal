/* FINTECPESSOAL — Flux Dark shell (vanilla, seguro para renderização). */
(function () {
  "use strict";

  var STORAGE_KEY = "fintecpessoal-theme";
  var PRIVACY_KEY = "fintecpessoal-privacy";
  var root = document.documentElement;
  var inited = false;

  function isDark() { return root.classList.contains("dark"); }

  function applyDark(dark) {
    root.classList.toggle("dark", dark);
    root.classList.toggle("light", !dark);
    try { localStorage.setItem(STORAGE_KEY, dark ? "dark" : "light"); } catch (e) {}
    updateThemeIcon();
  }

  function updateThemeIcon() {
    document.querySelectorAll("[data-theme-icon-sun]").forEach(function (s) {
      s.classList.toggle("hidden", !isDark());
    });
    document.querySelectorAll("[data-theme-icon-moon]").forEach(function (s) {
      s.classList.toggle("hidden", isDark());
    });
  }

  function applyPrivacy(on) {
    root.classList.toggle("privacy", on);
    var b = document.getElementById("privacy-toggle");
    if (b) {
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.classList.toggle("text-brand-400", on);
    }
    try { localStorage.setItem(PRIVACY_KEY, on ? "1" : "0"); } catch (e) {}
  }

  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem(STORAGE_KEY); } catch (e) {}
    applyDark(saved !== "light");
  }

  function initPrivacy() {
    var saved = null;
    try { saved = localStorage.getItem(PRIVACY_KEY); } catch (e) {}
    applyPrivacy(saved === "1");
  }

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else { fn(); }
  }

  onReady(function () {
    if (inited) return;
    inited = true;

    initTheme();
    initPrivacy();

    // ----- Tema -----
    document.querySelectorAll("[data-theme-toggle], [data-sidebar-inline-theme]").forEach(function (el) {
      el.addEventListener("click", function () { applyDark(!isDark()); });
    });

    // ----- Privacidade (botão + Shift+P) -----
    if (document.getElementById("privacy-toggle")) {
      document.getElementById("privacy-toggle").addEventListener("click", function () {
        applyPrivacy(!root.classList.contains("privacy"));
      });
    }
    document.addEventListener("keydown", function (e) {
      var t = e.target;
      var typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if (typing) return;
      if ((e.key === "P" || e.key === "p") && e.shiftKey) { e.preventDefault(); applyPrivacy(!root.classList.contains("privacy")); }
    });

    // ----- Sidebar drawer (mobile) -----
    var sidebar = document.getElementById("sidebar");
    var overlay = document.getElementById("sidebar-overlay");
    function openSidebar() {
      if (!sidebar) return;
      sidebar.classList.remove("-translate-x-full");
      overlay && overlay.classList.remove("hidden");
      document.body.classList.add("overflow-hidden");
      var ob = document.querySelector("[data-sidebar-open]");
      if (ob) ob.setAttribute("aria-expanded", "true");
    }
    function closeSidebar() {
      if (!sidebar) return;
      sidebar.classList.add("-translate-x-full");
      overlay && overlay.classList.add("hidden");
      document.body.classList.remove("overflow-hidden");
      var ob = document.querySelector("[data-sidebar-open]");
      if (ob) ob.setAttribute("aria-expanded", "false");
    }
    var sidebarOpen = document.querySelector("[data-sidebar-open]");
    var sidebarClose = document.querySelector("[data-sidebar-close]");
    if (sidebarOpen) sidebarOpen.addEventListener("click", openSidebar);
    if (sidebarClose) sidebarClose.addEventListener("click", closeSidebar);
    if (overlay) overlay.addEventListener("click", closeSidebar);

    // ----- Sheet "Mais" (mobile) -----
    var sheet = document.getElementById("more-sheet");
    var sheetOverlay = document.getElementById("more-sheet-overlay");
    function openMore() {
      if (!sheet) return;
      sheet.classList.remove("translate-y-full");
      sheetOverlay && sheetOverlay.classList.remove("hidden");
      var first = sheet.querySelector("[data-more-link]");
      if (first) first.focus();
    }
    function closeMore() {
      if (!sheet) return;
      sheet.classList.add("translate-y-full");
      sheetOverlay && sheetOverlay.classList.add("hidden");
    }
    var moreOpen = document.querySelector("[data-more-open]");
    var moreClose = document.querySelector("[data-more-close]");
    if (moreOpen) moreOpen.addEventListener("click", openMore);
    if (moreClose) moreClose.addEventListener("click", closeMore);
    if (sheetOverlay) sheetOverlay.addEventListener("click", closeMore);

    // ----- Command palette (Ctrl/Cmd+K) -----
    var palette = document.getElementById("command");
    var paletteInput = document.getElementById("command-input");
    var paletteBackdrop = document.getElementById("command-backdrop");
    var commandOpen = document.querySelector("[data-command-open]");

    function paletteItems() {
      if (!palette) return [];
      return Array.prototype.slice.call(palette.querySelectorAll("[data-palette-item]"));
    }
    function openPalette() {
      if (!palette) return;
      palette.classList.remove("hidden");
      paletteBackdrop && paletteBackdrop.classList.remove("hidden");
      document.body.classList.add("overflow-hidden");
      paletteItems().forEach(function (el) { el.classList.remove("hidden"); });
      if (paletteInput) { paletteInput.value = ""; setTimeout(function () { paletteInput.focus(); }, 10); }
      var last = palette.querySelector(".command-active");
      if (last) last.classList.remove("command-active");
    }
    function closePalette() {
      if (!palette) return;
      palette.classList.add("hidden");
      paletteBackdrop && paletteBackdrop.classList.add("hidden");
      document.body.classList.remove("overflow-hidden");
      if (paletteInput) paletteInput.blur();
    }

    if (commandOpen) commandOpen.addEventListener("click", openPalette);
    if (paletteBackdrop) paletteBackdrop.addEventListener("click", closePalette);

    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); }
      if (e.key === "Escape") { closePalette(); closeSidebar(); closeMore(); closeNotif(); }
    });

    function closeNotif() {
      var menu = document.getElementById("notif-menu");
      if (menu) menu.classList.add("hidden");
    }

    if (paletteInput) {
      paletteInput.addEventListener("input", function () {
        var q = paletteInput.value.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
        var items = paletteItems();
        var first = null;
        items.forEach(function (el) {
          var label = (el.getAttribute("data-label") || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
          el.classList.toggle("hidden", label.indexOf(q) === -1);
          if (!first && label.indexOf(q) !== -1) first = el;
        });
        items.forEach(function (el) { el.classList.remove("command-active"); });
        if (first) first.classList.add("command-active");
      });
      paletteInput.addEventListener("keydown", function (e) {
        var visible = paletteItems().filter(function (el) { return !el.classList.contains("hidden"); });
        if (visible.length === 0) return;
        var idx = visible.indexOf(palette.querySelector(".command-active"));
        if (e.key === "ArrowDown") {
          e.preventDefault();
          var next = (idx + 1) % visible.length;
          visible.forEach(function (el) { el.classList.remove("command-active"); });
          visible[next].classList.add("command-active");
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          var prev = (idx - 1 + visible.length) % visible.length;
          visible.forEach(function (el) { el.classList.remove("command-active"); });
          visible[prev].classList.add("command-active");
        } else if (e.key === "Enter") {
          e.preventDefault();
          var cur = palette.querySelector(".command-active");
          if (cur) cur.click();
        }
      });
    }

    // ----- Notificações -----
    var notifToggle = document.querySelector("[data-notif-toggle]");
    var notifMenu = document.getElementById("notif-menu");
    if (notifToggle) {
      notifToggle.addEventListener("click", function (e) {
        e.stopPropagation();
        if (notifMenu) notifMenu.classList.toggle("hidden");
      });
    }
    document.addEventListener("click", function (e) {
      if (e.target.closest("#notif-menu") || e.target.closest("[data-notif-toggle]")) return;
      closeNotif();
    });

    // ----- Dismiss de mensagens -----
    document.querySelectorAll("[data-dismiss-message]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var el = btn.closest(".alert");
        if (el) el.style.display = "none";
      });
    });
  });
})();