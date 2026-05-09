/* Live order total — works with Unfold stacked inlines, native selects, and Select2. */
(function () {
    "use strict";

    var PREFIX = "garments";

    function parseCatalogue() {
        var node = document.getElementById("ss-pricing-data");
        if (!node) return null;
        try {
            return JSON.parse(node.textContent || "{}");
        } catch (e) {
            return null;
        }
    }

    function fmt(amount) {
        return "€" + amount.toFixed(2);
    }

    function totalFormCount() {
        var el = document.getElementById("id_" + PREFIX + "-TOTAL_FORMS");
        if (!el) return 0;
        var n = parseInt(el.value, 10);
        return isNaN(n) ? 0 : n;
    }

    function fieldForRow(field, index) {
        var name = PREFIX + "-" + index + "-" + field;
        return (
            document.querySelector('select[name="' + name + '"]') ||
            document.querySelector('input[name="' + name + '"]')
        );
    }

    function collectRowIndices() {
        var seen = {};
        var rx = new RegExp("^" + PREFIX + "-(\\d+)-garment_type$");
        document.querySelectorAll("select[name], input[name]").forEach(function (el) {
            var m = (el.name || "").match(rx);
            if (m) seen[m[1]] = true;
        });
        var n = totalFormCount();
        for (var i = 0; i < n; i++) {
            if (fieldForRow("garment_type", i)) seen[String(i)] = true;
        }
        return Object.keys(seen).sort(function (a, b) {
            return parseInt(a, 10) - parseInt(b, 10);
        });
    }

    function compute(catalogue) {
        if (!catalogue) return 0;
        var gtypes = catalogue.garment_types || {};
        var mats = catalogue.materials || {};
        var total = 0;

        collectRowIndices().forEach(function (idx) {
            var delEl = fieldForRow("DELETE", idx);
            if (delEl && (delEl.checked || delEl.value === "on")) return;

            var gEl = fieldForRow("garment_type", idx);
            var mEl = fieldForRow("primary_material", idx);
            var qEl = fieldForRow("quantity", idx);

            var gtypeId = gEl ? gEl.value : "";
            var matId = mEl ? mEl.value : "";
            var qty = qEl ? parseInt(qEl.value, 10) : 0;
            if (!qty || isNaN(qty) || qty < 0) qty = 0;

            var base = gtypeId && gtypes[gtypeId] != null ? Number(gtypes[gtypeId]) : 0;
            var addon = matId && mats[matId] != null ? Number(mats[matId]) : 0;
            total += (base + addon) * qty;
        });

        return total;
    }

    function render(total) {
        var pill = document.getElementById("ss-live-total-pill");
        if (pill) {
            var pillValue = pill.querySelector("[data-ss-live-total]");
            if (pillValue) pillValue.textContent = fmt(total);
            pill.setAttribute("data-empty", total > 0 ? "false" : "true");
        }

        var ro =
            document.querySelector(".field-computed_total_display .readonly") ||
            document.querySelector(".field-computed_total_display [class*='readonly']");
        if (ro) {
            ro.textContent = fmt(total);
            ro.classList.add("ss-live-updated");
        }

        var tp = document.getElementById("id_total_price");
        if (tp && !tp.dataset.ssUserEdited) {
            tp.placeholder = "Auto: " + fmt(total);
        }
    }

    function wire(catalogue) {
        var run = function () {
            render(compute(catalogue));
        };

        document.addEventListener("change", function (e) {
            var t = e.target;
            var name = t && t.name ? t.name : "";
            if (
                new RegExp("^" + PREFIX + "-\\d+-garment_type$").test(name) ||
                new RegExp("^" + PREFIX + "-\\d+-primary_material$").test(name) ||
                new RegExp("^" + PREFIX + "-\\d+-quantity$").test(name) ||
                new RegExp("^" + PREFIX + "-\\d+-DELETE$").test(name)
            ) {
                run();
            }
        });

        document.addEventListener("input", function (e) {
            var t = e.target;
            if (t && t.name && new RegExp("^" + PREFIX + "-\\d+-quantity$").test(t.name)) {
                run();
            }
        });

        if (typeof jQuery !== "undefined") {
            ["select2:select", "select2:clear", "select2:unselect"].forEach(function (evt) {
                jQuery(document).on(evt, "select", function () {
                    var el = this;
                    if (el && el.name && new RegExp("^" + PREFIX + "-\\d+-").test(el.name)) {
                        run();
                    }
                });
            });
        }

        document.addEventListener("formset:added", run);
        document.addEventListener("formset:removed", run);

        var mo = new MutationObserver(function () {
            run();
        });
        var mg = document.getElementById(PREFIX + "-group");
        if (mg) {
            mo.observe(mg, { childList: true, subtree: true });
        }

        run();
    }

    document.addEventListener("DOMContentLoaded", function () {
        var cat = parseCatalogue();
        if (!cat) return;

        var tp = document.getElementById("id_total_price");
        if (tp) {
            tp.addEventListener("input", function () {
                tp.dataset.ssUserEdited = "1";
            });
        }

        wire(cat);
    });
})();
