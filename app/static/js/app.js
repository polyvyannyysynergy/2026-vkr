// Показ поля адреса только для способа получения «Почтой»
document.addEventListener("DOMContentLoaded", function () {
  var sel = document.getElementById("delivery");
  var box = document.getElementById("post-box");
  if (sel && box) {
    var sync = function () { box.style.display = sel.value === "POST" ? "" : "none"; };
    sel.addEventListener("change", sync); sync();
  }
  var st = document.getElementById("to_status");
  var hint = document.getElementById("reject-hint");
  if (st && hint) {
    var s2 = function () { hint.style.display = st.value === "REJ" ? "" : "none"; };
    st.addEventListener("change", s2); s2();
  }
  document.querySelectorAll("[data-print]").forEach(function (b) {
    b.addEventListener("click", function () { window.print(); });
  });
});
