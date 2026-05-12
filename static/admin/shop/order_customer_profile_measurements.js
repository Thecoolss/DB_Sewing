/* Prefill garment "Initial measurement" fields from the customer's saved profile when
 * the customer field changes (order add/change in admin). API: /internal/profile-measurements/<id>/
 */
(function () {
    "use strict";

    var PREFIX = "garments";

    function isOrderAdminPage() {
        var b = document.body;
        return (
            b &&
            b.classList.contains("app-shop") &&
            b.classList.contains("model-order") &&
            (b.classList.contains("change-form") || b.classList.contains("add-form"))
        );
    }

    function totalFormCount() {
        var el = document.getElementById("id_" + PREFIX + "-TOTAL_FORMS");
        if (!el) return 0;
        var n = parseInt(el.value, 10);
        return isNaN(n) ? 0 : n;
    }

    function fieldForRow(field, index) {
        var name = PREFIX + "-" + index + "-" + field;
        return document.querySelector('[name="' + name + '"]');
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
        return Object.keys(seen)
            .map(function (k) {
                return parseInt(k, 10);
            })
            .sort(function (a, b) {
                return a - b;
            });
    }

    function rowMarkedDeleted(idx) {
        var del = fieldForRow("DELETE", idx);
        return del && (del.checked || del.value === "on");
    }

    function setHint(html) {
        var el = document.getElementById("ss-customer-profile-measurements-hint");
        if (!el) return;
        el.innerHTML = html || "";
        el.style.display = html ? "block" : "none";
    }

    function apiUrl(customerId) {
        return "/internal/profile-measurements/" + customerId + "/";
    }

    function applyMeasurements(measurements) {
        if (!measurements || !measurements.length) {
            setHint("");
            return;
        }

        var lines = measurements.map(function (m) {
            return m.name + ": " + m.value + m.unit;
        });
        setHint(
            "<strong>Customer profile</strong> — " +
                lines.join("; ") +
                ". Suggested values were copied into empty garment rows below (edit as needed).",
        );

        var indices = collectRowIndices();
        var mi = 0;
        for (var j = 0; j < indices.length && mi < measurements.length; j++) {
            var idx = indices[j];
            if (rowMarkedDeleted(idx)) continue;

            var nameEl = fieldForRow("initial_measurement_name", idx);
            var valEl = fieldForRow("initial_measurement_value", idx);
            var unitEl = fieldForRow("initial_measurement_unit", idx);
            if (!nameEl || !valEl) continue;

            if ((nameEl.value || "").trim() !== "") continue;

            var m = measurements[mi];
            nameEl.value = m.name;
            valEl.value = m.value;
            if (unitEl) unitEl.value = m.unit || "cm";
            mi++;
        }
    }

    function syncCustomerProfile() {
        var cust = document.getElementById("id_customer");
        if (!cust) return;
        var id = cust.value;
        if (!id) {
            setHint("");
            return;
        }
        fetch(apiUrl(id), {
            method: "GET",
            credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest" },
        })
            .then(function (r) {
                if (!r.ok) throw new Error("bad response");
                return r.json();
            })
            .then(function (data) {
                applyMeasurements(data.measurements || []);
            })
            .catch(function () {
                setHint("");
            });
    }

    function ensureHintMount() {
        var group = document.getElementById(PREFIX + "-group");
        if (!group || document.getElementById("ss-customer-profile-measurements-hint")) return;

        var box = document.createElement("div");
        box.id = "ss-customer-profile-measurements-hint";
        box.className = "help";
        box.style.marginBottom = "12px";
        box.style.display = "none";
        group.parentNode.insertBefore(box, group);
    }

    document.addEventListener("DOMContentLoaded", function () {
        if (!isOrderAdminPage()) return;
        if (!document.getElementById("garments-group")) return;

        ensureHintMount();

        var cust = document.getElementById("id_customer");
        if (!cust) return;

        cust.addEventListener("change", syncCustomerProfile);

        if (typeof jQuery !== "undefined") {
            ["select2:select", "select2:clear", "select2:unselect"].forEach(function (evt) {
                jQuery(document).on(evt, "#id_customer", syncCustomerProfile);
            });
        }

        if (cust.value) syncCustomerProfile();

        document.addEventListener("formset:added", function () {
            if (cust.value) syncCustomerProfile();
        });
    });
})();
