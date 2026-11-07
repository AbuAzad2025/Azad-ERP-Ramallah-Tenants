(function () {
  "use strict";

  var meta = document.querySelector('meta[name="tenant-branch-id"]');
  var branchId = meta ? meta.getAttribute("content") : "";

  function warnIfCrossTenantSelect(select) {
    if (!branchId || !select || !select.options) return;
    select.addEventListener("change", function () {
      var opt = select.options[select.selectedIndex];
      if (!opt || !opt.dataset || !opt.dataset.branchId) return;
      if (String(opt.dataset.branchId) !== String(branchId)) {
        console.warn("tenant-scope: branch mismatch on", select.name || select.id);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll('select[name="branch_id"], select#branch_id').forEach(warnIfCrossTenantSelect);
  });
})();
