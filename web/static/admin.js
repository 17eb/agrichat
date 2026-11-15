// Admin panel behavior: loading state on navigation and the delete confirm dialog.
(function () {
  "use strict";

  var loading = document.querySelector(".loading-bar");

  function showLoading() {
    if (loading) {
      loading.hidden = false;
    }
  }

  window.addEventListener("pageshow", function () {
    if (loading) {
      loading.hidden = true;
    }
  });

  document.querySelectorAll("a.side-link, form[data-loading-form]").forEach(function (el) {
    el.addEventListener(el.tagName === "FORM" ? "submit" : "click", showLoading);
  });

  var dialog = document.getElementById("confirm-dialog");
  if (!dialog || typeof dialog.showModal !== "function") {
    return;
  }
  var pending = null;
  document.querySelectorAll("form[data-confirm-name]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (form.dataset.confirmed === "1") {
        showLoading();
        return;
      }
      event.preventDefault();
      pending = form;
      document.getElementById("confirm-name").textContent = form.dataset.confirmName;
      dialog.showModal();
    });
  });
  dialog.addEventListener("close", function () {
    if (dialog.returnValue === "confirm" && pending) {
      pending.dataset.confirmed = "1";
      pending.requestSubmit();
    }
    dialog.returnValue = "";
    pending = null;
  });
})();
