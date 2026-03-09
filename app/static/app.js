"use strict";

const summaryGrid = document.getElementById("summaryGrid");
const devicesContainer = document.getElementById("devicesContainer");
const historyContainer = document.getElementById("historyContainer");
const statusMessage = document.getElementById("statusMessage");
const discoverButton = document.getElementById("discoverButton");
const refreshButton = document.getElementById("refreshButton");
const toastContainer = document.getElementById("toastContainer");
const modalOverlay = document.getElementById("modalOverlay");

const summaryTemplate = document.getElementById("summaryCardTemplate");
const deviceTemplate = document.getElementById("deviceCardTemplate");
const outletTemplate = document.getElementById("outletCardTemplate");
const historyTemplate = document.getElementById("historyItemTemplate");

let isBusy = false;

/* ─── Confirmation presets ─── */

const CONFIRM = {
    on: {
        title: "Turn Outlet On?",
        titleClass: "",
        message: (name) => `You are about to turn on "${name}". Connected equipment will receive power.`,
        confirmLabel: "Turn On",
        confirmClass: "success-solid",
    },
    off: {
        title: "Warning — Turn Outlet Off?",
        titleClass: "danger",
        message: (name) =>
            `Turning off "${name}" will cut power immediately. Any connected equipment will lose power without a graceful shutdown.`,
        confirmLabel: "Turn Off",
        confirmClass: "danger-solid",
    },
    reboot: {
        title: "Warning — Reboot Outlet?",
        titleClass: "warning",
        message: (name) =>
            `Rebooting "${name}" will power-cycle the outlet. Connected equipment will restart and may lose unsaved data.`,
        confirmLabel: "Reboot Now",
        confirmClass: "warning-solid",
    },
    lock: {
        title: "Lock Outlet?",
        titleClass: "",
        message: (name) =>
            `Locking "${name}" will prevent anyone from turning it off or rebooting it remotely until the lock is removed.`,
        confirmLabel: "Lock Outlet",
        confirmClass: "primary",
    },
    unlock: {
        title: "Warning — Unlock Outlet?",
        titleClass: "warning",
        message: (name) =>
            `Removing the lock from "${name}" means it can be turned off or rebooted remotely again. Make sure this is intentional.`,
        confirmLabel: "Remove Lock",
        confirmClass: "danger-solid",
    },
};

/* ─── Utilities ─── */

function formatTimestamp(rawValue) {
    if (!rawValue) {
        return "—";
    }
    const date = new Date(rawValue);
    if (Number.isNaN(date.getTime())) {
        return rawValue;
    }
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    }).format(date);
}

function setStatus(message) {
    statusMessage.textContent = message;
}

function emptyState(text) {
    const container = document.createElement("div");
    container.className = "empty-state";
    container.textContent = text;
    return container;
}

/* ─── Toast notifications ─── */

function showToast(message, type) {
    const toast = document.createElement("div");
    toast.className = "toast toast-" + type;
    toast.textContent = message;
    toastContainer.prepend(toast);
    setTimeout(() => {
        toast.classList.add("leaving");
        toast.addEventListener("animationend", () => toast.remove());
    }, 4000);
}

/* ─── Confirmation modal (Promise-based) ─── */

function showConfirm(preset, outletName) {
    return new Promise((resolve) => {
        const titleEl = modalOverlay.querySelector(".modal-title");
        const messageEl = modalOverlay.querySelector(".modal-message");
        const confirmBtn = modalOverlay.querySelector(".modal-confirm");
        const cancelBtn = modalOverlay.querySelector(".modal-cancel");

        titleEl.textContent = preset.title;
        titleEl.className = "modal-title" + (preset.titleClass ? " " + preset.titleClass : "");
        messageEl.textContent = preset.message(outletName);
        confirmBtn.textContent = preset.confirmLabel;
        confirmBtn.className = "button " + preset.confirmClass;

        const controller = new AbortController();
        const signal = controller.signal;

        function close(accepted) {
            controller.abort();
            modalOverlay.classList.remove("visible");
            modalOverlay.setAttribute("aria-hidden", "true");
            document.body.classList.remove("modal-open");
            resolve(accepted);
        }

        confirmBtn.addEventListener("click", () => close(true), { signal });
        cancelBtn.addEventListener("click", () => close(false), { signal });
        modalOverlay.addEventListener("click", (e) => {
            if (e.target === modalOverlay) close(false);
        }, { signal });
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") close(false);
        }, { signal });

        modalOverlay.setAttribute("aria-hidden", "false");
        modalOverlay.classList.add("visible");
        document.body.classList.add("modal-open");
        cancelBtn.focus();
    });
}

/* ─── Rendering ─── */

function renderSummary(summary) {
    const cards = [
        ["Devices", summary.devices_total],
        ["Online", summary.devices_online],
        ["Outlets", summary.outlets_total],
        ["Powered On", summary.outlets_on],
        ["Locked", summary.outlets_locked],
    ];

    summaryGrid.replaceChildren(
        ...cards.map(([label, value]) => {
            const node = summaryTemplate.content.firstElementChild.cloneNode(true);
            node.querySelector(".summary-label").textContent = label;
            node.querySelector(".summary-value").textContent = String(value);
            return node;
        })
    );
}

function renderDevices(devices) {
    if (!devices.length) {
        devicesContainer.replaceChildren(
            emptyState("No compatible PDUs discovered yet. Use Discover Devices to scan the local HA host networks.")
        );
        return;
    }

    const nodes = devices.map((device) => {
        const node = deviceTemplate.content.firstElementChild.cloneNode(true);
        node.querySelector(".device-title").textContent = device.name;
        node.querySelector(".device-meta").textContent =
            device.outlets.length +
            " outlets detected" +
            " \u00B7 " +
            device.host +
            " \u00B7 " +
            (device.model || "Model not reported") +
            " \u00B7 Last seen " +
            formatTimestamp(device.last_seen_at);

        const statusPill = node.querySelector(".status-pill");
        statusPill.textContent = device.status;
        statusPill.dataset.status = device.status;

        const outletGrid = node.querySelector(".outlet-grid");
        const outletNodes = device.outlets.map((outlet) => {
            const outletNode = outletTemplate.content.firstElementChild.cloneNode(true);
            outletNode.querySelector(".outlet-name").textContent = outlet.name;
            outletNode.querySelector(".outlet-meta").textContent =
                "Port " + outlet.outlet_index + " \u00B7 Last change " + formatTimestamp(outlet.last_changed_at);

            const lockBadge = outletNode.querySelector(".lock-badge");
            lockBadge.textContent = outlet.is_locked ? "Remote-off locked" : "Unlocked";
            lockBadge.dataset.locked = String(outlet.is_locked);

            const stateBadge = outletNode.querySelector(".state-badge");
            stateBadge.textContent = outlet.current_state;
            stateBadge.dataset.state = outlet.current_state;

            outletNode.querySelectorAll("button[data-action]").forEach((button) => {
                const action = button.dataset.action;

                if (action === "toggle-lock") {
                    button.textContent = outlet.is_locked ? "Unlock" : "Lock";
                    button.addEventListener("click", () =>
                        confirmAndSetLock(outlet.id, !outlet.is_locked, outlet.name)
                    );
                    return;
                }

                if (outlet.is_locked && (action === "off" || action === "reboot")) {
                    button.disabled = true;
                    button.title = "Outlet is locked — unlock first";
                }

                button.addEventListener("click", () =>
                    confirmAndSendCommand(outlet.id, action, outlet.name)
                );
            });

            return outletNode;
        });

        outletGrid.replaceChildren(...outletNodes);
        return node;
    });

    devicesContainer.replaceChildren(...nodes);
}

function renderHistory(history) {
    if (!history.length) {
        historyContainer.replaceChildren(
            emptyState("No outlet activity has been recorded yet.")
        );
        return;
    }

    const nodes = history.map((eventItem) => {
        const node = historyTemplate.content.firstElementChild.cloneNode(true);
        node.querySelector(".history-title").textContent =
            eventItem.device_name + " \u00B7 " + eventItem.outlet_name;
        node.querySelector(".history-meta").textContent =
            eventItem.action + " from " + eventItem.source + " \u00B7 " + formatTimestamp(eventItem.created_at);

        const transition = [eventItem.previous_state, eventItem.next_state].filter(Boolean).join(" \u2192 ");
        node.querySelector(".history-message").textContent = transition || eventItem.message || "No message";
        return node;
    });

    historyContainer.replaceChildren(...nodes);
}

/* ─── API helpers ─── */

async function requestJson(url, options) {
    const headers = {};
    if (options && options.body) {
        headers["Content-Type"] = "application/json";
    }
    const response = await fetch(url, { ...options, headers });

    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || payload.message || "Request failed.");
    }
    return response.json();
}

async function loadOverview() {
    try {
        const payload = await requestJson("/api/overview");
        renderSummary(payload.summary);
        renderDevices(payload.devices);
        renderHistory(payload.history);
        setStatus("Last refreshed " + new Date().toLocaleTimeString());
    } catch (error) {
        setStatus("Failed to load — " + error.message);
    }
}

/* ─── Busy state wrapper ─── */

async function withBusyState(work) {
    if (isBusy) {
        return;
    }
    isBusy = true;
    document.body.classList.add("busy");
    try {
        await work();
    } catch (error) {
        showToast(error.message, "error");
    } finally {
        isBusy = false;
        document.body.classList.remove("busy");
    }
}

/* ─── Actions (confirm then execute) ─── */

async function confirmAndSendCommand(outletId, action, outletName) {
    const preset = CONFIRM[action];
    if (!preset) {
        return;
    }

    const accepted = await showConfirm(preset, outletName);
    if (!accepted) {
        return;
    }

    await withBusyState(async () => {
        setStatus("Sending " + action + "\u2026");
        const result = await requestJson("/api/outlets/" + outletId + "/command", {
            method: "POST",
            body: JSON.stringify({ action }),
        });
        showToast(result.message || "Command accepted.", "success");
        await loadOverview();
    });
}

async function confirmAndSetLock(outletId, locked, outletName) {
    const preset = locked ? CONFIRM.lock : CONFIRM.unlock;

    const accepted = await showConfirm(preset, outletName);
    if (!accepted) {
        return;
    }

    await withBusyState(async () => {
        setStatus(locked ? "Locking outlet\u2026" : "Unlocking outlet\u2026");
        const result = await requestJson("/api/outlets/" + outletId + "/lock", {
            method: "POST",
            body: JSON.stringify({ locked }),
        });
        showToast(result.message || "Lock updated.", "success");
        await loadOverview();
    });
}

/* ─── Top-level buttons ─── */

discoverButton.addEventListener("click", async () => {
    await withBusyState(async () => {
        setStatus("Scanning local networks for compatible PDUs\u2026");
        await requestJson("/api/devices/discover", { method: "POST" });
        showToast("Discovery scan complete.", "success");
        await loadOverview();
    });
});

refreshButton.addEventListener("click", () => {
    void loadOverview();
});

/* ─── Initial load + auto-refresh ─── */

void loadOverview();
setInterval(() => {
    if (!isBusy && !document.body.classList.contains("modal-open")) {
        void loadOverview();
    }
}, 10000);
