"use strict";

// ─────────────────────────────────────────────────────────────────
// INIT: Restore state when popup opens
// ─────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
    const stored = await chrome.storage.local.get(["saas_jwt_token", "autoScanEnabled"]);

    if (stored.saas_jwt_token) {
        showActionSection();
    }

    // Restore Auto Scan button state
    setAutoScanButtonState(!!stored.autoScanEnabled);
});

// ─────────────────────────────────────────────────────────────────
// 1. LOGIN
// ─────────────────────────────────────────────────────────────────
document.getElementById("loginBtn").addEventListener("click", async () => {
    const st    = document.getElementById("status");
    const email = document.getElementById("extEmail").value.trim();
    const pass  = document.getElementById("extPass").value.trim();

    if (!email || !pass) { setStatus("❌ Enter Email & Password.", "red"); return; }
    setStatus("⏳ Logging in...", "#0a66c2");

    try {
        const authResp = await fetch(
            "https://ai-job-agent-backend-qmq1.onrender.com/api/auth/login",
            { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password: pass }) }
        );
        const authData = await authResp.json();
        if (!authResp.ok || !authData.token) { setStatus("❌ Login failed.", "red"); return; }

        await chrome.storage.local.set({
            saas_jwt_token: authData.token,
            saas_user_info: { user_id: authData.user_id, email: authData.email },
        });

        showActionSection();
        setStatus("✅ Logged in & Ready!", "green");
    } catch (err) {
        setStatus("❌ Backend connection error.", "red");
    }
});


// ─────────────────────────────────────────────────────────────────
// 3. START CAMPAIGN (apply to jobs visible on current page)
// ─────────────────────────────────────────────────────────────────
document.getElementById("startCampaignBtn").addEventListener("click", async () => {
    setStatus("🔍 Finding LinkedIn Jobs tab...", "#0a66c2");

    let allTabs = await chrome.tabs.query({ url: "*://www.linkedin.com/jobs/*" });
    if (!allTabs.length) allTabs = await chrome.tabs.query({ url: "*://www.linkedin.com/*" });
    const tab = allTabs.find((t) => t.url && t.url.includes("linkedin.com/jobs"));

    if (!tab) { setStatus("❌ Open a LinkedIn Jobs page first.", "red"); return; }

    // 🌟 FIX: Extract the manual search keywords and location from the current URL
    let manualKeywords = "";
    let manualLocation = "";
    try {
        const urlObj = new URL(tab.url);
        manualKeywords = urlObj.searchParams.get("keywords") || "";
        manualLocation = urlObj.searchParams.get("location") || "";
    } catch(e) {}

    setStatus("⏳ Syncing search context...", "#0a66c2");
    
    // Always overwrite (even with empty strings) so a stale search from an old campaign is never reused
    await chrome.storage.local.set({
        manualCampaignRole: manualKeywords,
        manualCampaignLocation: manualLocation
    });

    setStatus("⏳ Sending start signal...", "#0a66c2");
    chrome.tabs.sendMessage(tab.id, { action: "start_same_tab_campaign" }, (resp) => {
        if (chrome.runtime.lastError || !resp) {
            setStatus("⚠️ Refresh LinkedIn & try again.", "#b45309");
            return;
        }
        setStatus("🚀 Campaign running!", "green");
        setTimeout(() => window.close(), 1500);
    });
});

// ─────────────────────────────────────────────────────────────────
// 4. AUTO SCAN TOGGLE
// ─────────────────────────────────────────────────────────────────
document.getElementById("autoScanBtn").addEventListener("click", async () => {
    const stored = await chrome.storage.local.get(["autoScanEnabled"]);
    const isCurrentlyEnabled = !!stored.autoScanEnabled;

    if (isCurrentlyEnabled) {
        // STOP
        chrome.runtime.sendMessage({ action: "STOP_AUTO_SCAN" }, () => {
            setAutoScanButtonState(false);
            setStatus("⏹️ Auto Scan stopped.", "gray");
        });
    } else {
        // START — make sure profile prefs are loaded first
        setStatus("⏳ Starting Auto Scan...", "#7c3aed");
        await fetchAndStorePrefs();

        chrome.runtime.sendMessage({ action: "START_AUTO_SCAN" }, () => {
            setAutoScanButtonState(true);
            setStatus("🔍 Auto Scan active! Checks every 5 mins.", "#7c3aed");
        });
    }
});

// ─────────────────────────────────────────────────────────────────
// 5. LOGOUT
// ─────────────────────────────────────────────────────────────────
document.getElementById("logoutBtn").addEventListener("click", async () => {
    // Stop auto scan if running before logout
    chrome.runtime.sendMessage({ action: "STOP_AUTO_SCAN" }, () => {});

    await chrome.storage.local.remove(["saas_jwt_token", "saas_user_info", "autoScanEnabled", "targetRoles", "targetLocations"]);
    document.getElementById("loginSection").classList.remove("hidden");
    document.getElementById("actionSection").classList.add("hidden");
    setStatus("🚪 Logged out.", "gray");
});

// ─────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────

function showActionSection() {
    document.getElementById("loginSection").classList.add("hidden");
    document.getElementById("actionSection").classList.remove("hidden");
    setStatus("✅ Logged in & Ready.", "green");
}

function setStatus(msg, color) {
    const el = document.getElementById("status");
    el.innerText = msg;
    el.style.color = color;
}

function setAutoScanButtonState(enabled) {
    const btn  = document.getElementById("autoScanBtn");
    const hint = document.getElementById("autoScanHint");

    if (enabled) {
        btn.innerText = "⏹️ Stop Auto Scan";
        btn.classList.add("active");
        hint.innerText = "🟢 Running — scanning LinkedIn every 5 mins and auto-applying to new jobs.";
        hint.style.color = "#16a34a";
    } else {
        btn.innerText = "🔍 Start Auto Scan";
        btn.classList.remove("active");
        hint.innerText = "Scans LinkedIn every 5 mins for new jobs matching your profile and applies automatically.";
        hint.style.color = "#64748b";
    }
}

/**
 * Fetches the user's target roles + locations from the backend
 * and stores them in chrome.storage for background.js to use.
 */
async function fetchAndStorePrefs() {
    try {
        const stored = await chrome.storage.local.get(["saas_jwt_token"]);
        if (!stored.saas_jwt_token) return;

        const resp = await fetch(
            "https://ai-job-agent-backend-qmq1.onrender.com/api/profile",
            { headers: { Authorization: "Bearer " + stored.saas_jwt_token } }
        );
        if (!resp.ok) return;

        const data = await resp.json();
        const profile = data.profile || {};

        const updates = {};
        if (profile.target_roles) {
            try { updates.targetRoles = JSON.parse(profile.target_roles); } catch (e) {}
        }
        if (profile.target_locations) {
            try { updates.targetLocations = JSON.parse(profile.target_locations); } catch (e) {}
        }

        if (Object.keys(updates).length > 0) {
            await chrome.storage.local.set(updates);
            console.log("[AutoScan] Stored prefs:", updates);
        }
    } catch (e) {
        console.warn("[AutoScan] Could not fetch prefs:", e);
    }
}