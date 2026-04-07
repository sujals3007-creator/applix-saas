// popup.js — AI Job Agent — DEFINITIVE VERSION
// Self-contained. Zero external dependencies.
// All auth, cookie, and UI logic defined here.
// MV3 CSP compliant: loaded via <script src="popup.js"> only.

"use strict";

// ─────────────────────────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────────────────────────
const API   = "https://ai-job-agent-backend-qmq1.onrender.com";
const TK    = "saas_jwt_token";
const UK    = "saas_user_info";
const LI_AT = "linkedin_li_at";
const LI_JS = "linkedin_jsessionid";
const LI_SA = "linkedin_cookies_saved_at";

// ─────────────────────────────────────────────────────────────────
// AUTH
// ─────────────────────────────────────────────────────────────────

async function getStoredToken() {
    const d = await chrome.storage.local.get([TK, UK]);
    return { token: d[TK] || null, user: d[UK] || null };
}

async function isLoggedIn() {
    const { token } = await getStoredToken();
    return Boolean(token);
}

async function getAuthHeader() {
    const { token } = await getStoredToken();
    return token ? { "Authorization": "Bearer " + token } : {};
}

async function _storeSession(data) {
    await chrome.storage.local.set({
        [TK]: data.token,
        [UK]: { user_id: data.user_id, email: data.email, full_name: data.full_name },
    });
}

async function login(email, password) {
    try {
        const r = await fetch(API + "/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
        });
        const d = await r.json();
        if (d.token) await _storeSession(d);
        return d;
    } catch {
        return { detail: "Cannot reach server. Is Python running on port 8000?" };
    }
}

async function signup(email, password, fullName) {
    try {
        const r = await fetch(API + "/api/auth/signup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                email: email.trim().toLowerCase(),
                password,
                full_name: (fullName || "").trim(),
            }),
        });
        const d = await r.json();
        if (d.token) await _storeSession(d);
        return d;
    } catch {
        return { detail: "Cannot reach server. Is Python running on port 8000?" };
    }
}

async function logout() {
    await chrome.storage.local.remove([TK, UK]);
}

// ─────────────────────────────────────────────────────────────────
// COOKIES
// ─────────────────────────────────────────────────────────────────

async function saveCookies(liAt, jsessionid) {
    await chrome.storage.local.set({
        [LI_AT]: liAt.trim(),
        [LI_JS]: jsessionid.trim(),
        [LI_SA]: new Date().toISOString(),
    });
    try {
        const r = await fetch(API + "/api/save-cookies", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ li_at: liAt.trim(), jsessionid: jsessionid.trim() }),
        });
        const d = await r.json();
        return { success: true, message: d.status === "success" ? "Saved!" : "Saved locally." };
    } catch {
        return { success: true, message: "Saved locally. Start Python to sync." };
    }
}

async function loadCookies() {
    const d = await chrome.storage.local.get([LI_AT, LI_JS, LI_SA]);
    return { liAt: d[LI_AT] || "", jsessionid: d[LI_JS] || "", savedAt: d[LI_SA] || null };
}

async function areCookiesSaved() {
    const { liAt, jsessionid } = await loadCookies();
    return liAt.length > 0 && jsessionid.length > 0;
}

async function getCookieAge() {
    const { savedAt } = await loadCookies();
    if (!savedAt) return { ageText: "Never saved", shouldWarn: true };
    const h = Math.floor((Date.now() - new Date(savedAt).getTime()) / 3600000);
    const d = Math.floor(h / 24);
    const ageText = h < 1 ? "Just saved" : h < 24 ? h + "h ago" : d + "d ago";
    return { ageText, shouldWarn: d >= 3 };
}

async function validateCookiesViaBackend() {
    try {
        const r = await fetch(API + "/api/validate-cookies");
        const d = await r.json();
        return { valid: d.status === "valid", reason: d.reason };
    } catch {
        return { valid: false, reason: "backend_offline" };
    }
}

// ─────────────────────────────────────────────────────────────────
// UI HELPERS
// ─────────────────────────────────────────────────────────────────

async function showMainScreen() {
    document.getElementById("authScreen").style.display = "none";
    document.getElementById("mainScreen").style.display = "block";

    const { user } = await getStoredToken();
    if (user) document.getElementById("userLabel").innerText = user.full_name || user.email;

    const c = await loadCookies();
    if (c.liAt)       document.getElementById("liAtInput").value       = c.liAt;
    if (c.jsessionid) document.getElementById("jsessionidInput").value = c.jsessionid;

    const { ageText, shouldWarn } = await getCookieAge();
    const ageEl = document.getElementById("cookieAge");
    ageEl.innerText   = ageText === "Never saved"
        ? "No cookies saved yet."
        : "Last saved: " + ageText + (shouldWarn ? " — refresh!" : "");
    ageEl.style.color = shouldWarn ? "#b45309" : "#888";

    await loadSavedProfile();
}

async function loadSavedProfile() {
    try {
        const h = await getAuthHeader();
        if (!h["Authorization"]) return;
        const r = await fetch(API + "/api/profile", { headers: h });
        const d = await r.json();
        if (d.status !== "success" || !d.profile) return;
        const p = d.profile;
        if (p.target_roles) {
            try {
                const roles = typeof p.target_roles === "string"
                    ? JSON.parse(p.target_roles) : p.target_roles;
                document.getElementById("targetRoles").value = roles.join(", ");
            } catch {}
        }
        if (p.skills)             document.getElementById("skills").value       = p.skills;
        if (p.years_experience)   document.getElementById("yearsExp").value     = p.years_experience;
        if (p.current_ctc_inr)    document.getElementById("currentCtc").value   = p.current_ctc_inr;
        if (p.expected_ctc_inr)   document.getElementById("expectedCtc").value  = p.expected_ctc_inr;
        if (p.notice_period_days) document.getElementById("noticePeriod").value = p.notice_period_days;
        if (p.sender_email)       document.getElementById("senderEmail").value  = p.sender_email;
        // 🌟 NEW SaaS FIELDS:
        if (p.app_password)       document.getElementById("appPassword").value  = p.app_password;
        if (p.key_achievements)   document.getElementById("keyAchievements").value = p.key_achievements;
        if (p.why_good_fit)       document.getElementById("whyGoodFit").value   = p.why_good_fit;
    } catch (e) {
        console.warn("[Popup] loadSavedProfile:", e);
    }
}

// ─────────────────────────────────────────────────────────────────
// BOOT + EVENT LISTENERS
// ─────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async function () {
    console.log("[Popup] Loaded.");

    if (await isLoggedIn()) {
        await showMainScreen();
    }

    // ── AUTH BUTTONS ─────────────────────────────────────────────

    var signupMode = false;

    document.getElementById("signupToggle").addEventListener("click", function () {
        signupMode = !signupMode;
        document.getElementById("nameRow").style.display  = signupMode ? "block" : "none";
        document.getElementById("loginBtn").innerText     = signupMode ? "Create Account" : "Login";
        document.getElementById("signupToggle").innerText = signupMode ? "← Back to Login" : "Create Account";
        document.getElementById("authMsg").innerText      = "";
    });

    document.getElementById("loginBtn").addEventListener("click", async function () {
        var msg      = document.getElementById("authMsg");
        var email    = document.getElementById("authEmail").value.trim();
        var pw       = document.getElementById("authPassword").value;
        var fullName = document.getElementById("authName").value.trim();

        if (!email || !pw) {
            msg.innerText = "❌ Please fill in email and password.";
            msg.style.color = "red";
            return;
        }
        msg.innerText   = "⏳ Please wait...";
        msg.style.color = "#0a66c2";

        var result = signupMode
            ? await signup(email, pw, fullName || email.split("@")[0])
            : await login(email, pw);

        if (result.token) {
            await showMainScreen();
        } else {
            msg.innerText   = "❌ " + (result.detail || "Authentication failed.");
            msg.style.color = "red";
        }
    });

    document.getElementById("logoutBtn").addEventListener("click", async function () {
        await logout();
        document.getElementById("mainScreen").style.display = "none";
        document.getElementById("authScreen").style.display = "block";
        document.getElementById("authMsg").innerText        = "";
        document.getElementById("authEmail").value          = "";
        document.getElementById("authPassword").value       = "";
    });

    // ── RESUME UPLOAD ─────────────────────────────────────────────

    // ── RESUME UPLOAD ─────────────────────────────────────────────

    document.getElementById("uploadBtn").addEventListener("click", async function () {
        var fi = document.getElementById("resumeFile");
        var st = document.getElementById("status");
        if (!fi.files.length) { st.innerText = "❌ Select a PDF first."; st.style.color = "red"; return; }
        
        var fd = new FormData();
        fd.append("file", fi.files[0]);
        st.innerText = "⏳ Uploading..."; st.style.color = "#0a66c2";
        
        try {
            var h = await getAuthHeader(); // 🌟 FIX: Grab the user's login token
            
            var r = await fetch(API + "/api/upload-resume", { 
                method: "POST", 
                headers: h, // 🌟 FIX: Attach the token to the request!
                body: fd 
            });
            var d = await r.json();
            
            // Handle FastAPI security rejection gracefully
            if (!r.ok) {
                st.innerText = "❌ " + (d.detail || d.message || "Upload failed");
                st.style.color = "red";
                return;
            }

            st.innerText   = d.status === "success" ? "✅ Brain initialized!" : "❌ " + (d.message || "Error");
            st.style.color = d.status === "success" ? "green" : "red";
        } catch (e) {
            st.innerText = "❌ Server error. Is Python running?"; st.style.color = "red";
        }
    });

    // ── COOKIES ───────────────────────────────────────────────────

    document.getElementById("saveCookiesBtn").addEventListener("click", async function () {
        var st         = document.getElementById("cookieStatus");
        var liAt       = document.getElementById("liAtInput").value.trim();
        var jsessionid = document.getElementById("jsessionidInput").value.trim();
        if (!liAt || !jsessionid) { st.innerText = "❌ Fill in both fields."; st.style.color = "red"; return; }
        st.innerText = "⏳ Saving..."; st.style.color = "#0f7490";
        var result = await saveCookies(liAt, jsessionid);
        st.innerText   = result.success ? "✅ " + result.message : "❌ " + result.message;
        st.style.color = result.success ? "green" : "red";
    });

    document.getElementById("validateCookiesBtn").addEventListener("click", async function () {
        var st = document.getElementById("cookieStatus");
        if (!(await areCookiesSaved())) {
            st.innerText = "❌ Paste and save cookies first."; st.style.color = "red"; return;
        }
        st.innerText = "⏳ Testing..."; st.style.color = "#0f7490";
        var result = await validateCookiesViaBackend();
        if (result.valid) { st.innerText = "✅ Cookies working!"; st.style.color = "green"; return; }
        var msgs = {
            expired:         "❌ Expired — get fresh ones.",
            missing:         "❌ Not set.",
            rate_limited:    "⚠️ Throttled — wait 2 min.",
            backend_offline: "❌ Python not running.",
        };
        st.innerText   = msgs[result.reason] || "❌ Failed: " + result.reason;
        st.style.color = result.reason === "rate_limited" ? "#b45309" : "red";
    });

    // ── SAVE PROFILE ──────────────────────────────────────────────

    document.getElementById("saveProfileBtn").addEventListener("click", async function () {
        var st = document.getElementById("status");
        st.innerText = "⏳ Saving profile..."; st.style.color = "#7c3aed";
        var roles = document.getElementById("targetRoles").value
            .split(",").map(function (r) { return r.trim(); }).filter(Boolean);
        var payload = {
            li_at:              document.getElementById("liAtInput").value.trim(),
            jsessionid:         document.getElementById("jsessionidInput").value.trim(),
            target_roles:       roles.length ? roles : ["AI Engineer"],
            skills:             document.getElementById("skills").value.trim(),
            years_experience:   parseFloat(document.getElementById("yearsExp").value)   || 0,
            current_ctc_inr:    parseInt(document.getElementById("currentCtc").value)   || 0,
            expected_ctc_inr:   parseInt(document.getElementById("expectedCtc").value)  || 0,
            notice_period_days: parseInt(document.getElementById("noticePeriod").value) || 30,
            sender_email:       document.getElementById("senderEmail").value.trim(),
            sender_phone:       "", // Hidden for now
            // 🌟 NEW SaaS FIELDS:
            app_password:       document.getElementById("appPassword").value.trim(),
            key_achievements:   document.getElementById("keyAchievements").value.trim(),
            why_good_fit:       document.getElementById("whyGoodFit").value.trim()
        };
        try {
            var h = await getAuthHeader();
            var r = await fetch(API + "/api/profile/save", {
                method: "POST",
                headers: Object.assign({ "Content-Type": "application/json" }, h),
                body: JSON.stringify(payload),
            });
            var d = await r.json();
            st.innerText   = d.status === "success" ? "✅ Profile saved!" : "❌ " + (d.message || "Failed");
            st.style.color = d.status === "success" ? "green" : "red";
        } catch {
            st.innerText = "❌ Server error."; st.style.color = "red";
        }
    });

    // ── AUTO-MONITOR ─────────────────────────────────────────────

    document.getElementById("startAutoBtn").addEventListener("click", async function () {
        var st  = document.getElementById("autoStatus");
        var btn = document.getElementById("startAutoBtn");

        var tabs = await chrome.tabs.query({ url: "*://*.linkedin.com/*" });
        if (!tabs.length) {
            st.innerText = "⚠️ Open LinkedIn in a tab first."; st.style.color = "#b45309"; return;
        }
        st.innerText = "⏳ Starting auto-monitor..."; st.style.color = "#0a66c2";

        chrome.tabs.sendMessage(tabs[0].id, { action: "start_auto_trigger" }, function (resp) {
            if (chrome.runtime.lastError || !resp) {
                st.innerText = "⚠️ Refresh the LinkedIn page then try again.";
                st.style.color = "#b45309";
                return;
            }
            st.innerText   = resp.status === "already_running"
                ? "✅ Already running — polling every 30s."
                : "✅ Auto-monitor started! Polling every 30s.";
            st.style.color = "green";
            btn.innerText  = "Auto-Monitor Running ✓";
            btn.style.background = "#064e3b";
        });
    });

    // ── MANUAL CAMPAIGN ───────────────────────────────────────────
    // Sends start_same_tab_campaign to content.js which runs the full
    // campaign loop directly on the LinkedIn Jobs Search page —
    // no tab navigation, no new tabs, everything stays in place.

    document.getElementById("startCampaignBtn").addEventListener("click", async function () {
        var st = document.getElementById("status");
        st.innerText = "🔍 Finding LinkedIn Jobs tab..."; st.style.color = "#0a66c2";

        var allTabs = await chrome.tabs.query({ url: "*://www.linkedin.com/jobs/*" });
        if (!allTabs.length) allTabs = await chrome.tabs.query({ url: "*://www.linkedin.com/*" });
        var tab = allTabs.find(function (t) { return t.url && t.url.includes("linkedin.com/jobs"); });

        if (!tab) {
            st.innerText   = "❌ Open a LinkedIn Jobs Search page first.";
            st.style.color = "red";
            return;
        }

        st.innerText = "⏳ Sending campaign start signal..."; st.style.color = "#0a66c2";

        chrome.tabs.sendMessage(tab.id, { action: "start_same_tab_campaign" }, function (resp) {
            if (chrome.runtime.lastError || !resp) {
                st.innerText   = "⚠️ Refresh the LinkedIn Jobs page then click again.";
                st.style.color = "#b45309";
                return;
            }
            st.innerText   = "🚀 Campaign running! Watch the LinkedIn tab.";
            st.style.color = "green";
            document.getElementById("startCampaignBtn").innerText = "⏳ Running...";
            
            // This line instantly closes the popup so you can watch the agent work
            setTimeout(() => window.close(), 1500); 
        });
    });

}); // end DOMContentLoaded