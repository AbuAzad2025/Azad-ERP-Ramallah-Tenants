(function () {
  "use strict";

  function initAuthBg() {
    var body = document.body;
    if (!body) return;
    var bg = body.getAttribute("data-auth-bg");
    if (bg) {
      body.style.setProperty("--erp-public-bg-image", "url(" + bg + ")");
    }
  }

  function initDrawer() {
    var drawer = document.getElementById("erpPublicDrawer");
    var backdrop = document.getElementById("erpPublicDrawerBackdrop");
    var openBtn = document.getElementById("erpPublicDrawerBtn");
    var closeBtn = document.getElementById("erpPublicDrawerClose");
    if (!drawer || !backdrop) return;

    function open() {
      drawer.classList.add("is-open");
      drawer.setAttribute("aria-hidden", "false");
      backdrop.hidden = false;
      document.body.classList.add("erp-drawer-open");
    }

    function close() {
      drawer.classList.remove("is-open");
      drawer.setAttribute("aria-hidden", "true");
      backdrop.hidden = true;
      document.body.classList.remove("erp-drawer-open");
    }

    if (openBtn) openBtn.addEventListener("click", open);
    if (closeBtn) closeBtn.addEventListener("click", close);
    backdrop.addEventListener("click", close);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initAuthBg();
    initDrawer();
  });
})();
