// saas_content.js
// ONE file that replaces: auth_manager.js + cookie_manager.js + content_hook.js + auto_trigger.js
// No load guards. No if-blocks. Direct window assignments throughout.
// All auth, cookie, hook and auto-trigger logic is here.

(function() {
    "use strict";

    const API      = "https://ai-job-agent-backend-qmq1.onrender.com";
    const TK       = "saas_jwt_token";
    const UK       = "saas_user_info";
    const LI_AT    = "linkedin_li_at";
    const LI_JS    = "linkedin_jsessionid";
    const LI_SAVED = "linkedin_cookies_saved_at";

    // ── AUTH ─────────────────────────────────────────────────────────

    window.getStoredToken = async function() {
        const d = await chrome.storage.local.get([TK, UK]);
        return { token: d[TK] || null, user: d[UK] || null };
    };

    window.isLoggedIn = async function() {
        const { token } = await window.getStoredToken();
        return Boolean(token);
    };

    window.getAuthHeader = async function() {
        const { token } = await window.getStoredToken();
        return token ? { "Authorization": "Bearer " + token } : {};
    };

    async function _storeSession(d) {
        await chrome.storage.local.set({
            [TK]: d.token,
            [UK]: { user_id: d.user_id, email: d.email, full_name: d.full_name },
        });
    }

    window.login = async function(email, password) {
        try {
            const r = await fetch(API + "/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
            });
            const d = await r.json();
            if (d.token) await _storeSession(d);
            return d;
        } catch { return { detail: "Cannot reach server. Is Python running?" }; }
    };

    window.signup = async function(email, password, fullName) {
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
        } catch { return { detail: "Cannot reach server. Is Python running?" }; }
    };

    window.logout = async function() {
        await chrome.storage.local.remove([TK, UK]);
    };

    // ── COOKIES ──────────────────────────────────────────────────────

    window.saveCookies = async function(liAt, jsessionid) {
        if (!liAt || liAt.trim().length < 20)
            return { success: false, message: "li_at value too short." };
        if (!jsessionid || jsessionid.trim().length < 5)
            return { success: false, message: "JSESSIONID empty." };

        await chrome.storage.local.set({
            [LI_AT]:    liAt.trim(),
            [LI_JS]:    jsessionid.trim(),
            [LI_SAVED]: new Date().toISOString(),
        });

        try {
            const r = await fetch(API + "/api/save-cookies", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ li_at: liAt.trim(), jsessionid: jsessionid.trim() }),
            });
            const d = await r.json();
            return { success: true, message: d.status === "success"
                ? "Saved to extension and backend."
                : "Saved locally. Backend: " + d.message };
        } catch {
            return { success: true, message: "Saved locally. Start Python server to sync." };
        }
    };

    window.loadCookies = async function() {
        const d = await chrome.storage.local.get([LI_AT, LI_JS, LI_SAVED]);
        return {
            liAt:       d[LI_AT]    || "",
            jsessionid: d[LI_JS]    || "",
            savedAt:    d[LI_SAVED] || null,
        };
    };

    window.areCookiesSaved = async function() {
        const { liAt, jsessionid } = await window.loadCookies();
        return liAt.length > 0 && jsessionid.length > 0;
    };

    window.getCookieAge = async function() {
        const { savedAt } = await window.loadCookies();
        if (!savedAt) return { ageText: "Never saved", shouldWarn: true };
        const diffH = Math.floor((Date.now() - new Date(savedAt).getTime()) / 3600000);
        const diffD = Math.floor(diffH / 24);
        const ageText = diffH < 1 ? "Just saved"
            : diffH < 24 ? diffH + " hour" + (diffH > 1 ? "s" : "") + " ago"
            : diffD + " day" + (diffD > 1 ? "s" : "") + " ago";
        return { ageText, shouldWarn: diffD >= 3 };
    };

    window.validateCookiesViaBackend = async function() {
        try {
            const r = await fetch(API + "/api/validate-cookies");
            const d = await r.json();
            return { valid: d.status === "valid", reason: d.reason, message: d.message };
        } catch {
            return { valid: false, reason: "backend_offline", message: "Backend not running." };
        }
    };

    // ── AUTO-TRIGGER (polls backend for queued jobs) ──────────────────

    let _pollTimer  = null;
    let _pollActive = false;

    function _startPolling() {
        if (_pollActive) return;
        _pollActive = true;
        console.log("[SaasContent] Auto-trigger polling started.");

        // Poll the backend every 15 seconds for jobs found by the 5-minute python scanner
        _pollTimer = setInterval(async function() {
            try {
                const headers = await window.getAuthHeader();
                if (!headers["Authorization"]) return;

                const resp = await fetch(API + "/api/pending-jobs", { headers });
                if (!resp.ok) return;
                const data = await resp.json();

                if (data && data.jobs && data.jobs.length > 0) {
                    console.log(`[SaasContent] Found ${data.jobs.length} auto-scanned jobs! Injecting to queue...`);
                    
                    // Convert the backend job data into raw URLs
                    const urls = data.jobs.map(j => j.job_url || `https://www.linkedin.com/jobs/view/${j.job_id}/`);
                    
                    // 🌟 THE UNIFIED FIX: Inject the 5-minute jobs directly into the Watchdog Queue!
                    chrome.runtime.sendMessage({ action: "start_campaign", urls: urls }, (response) => {
                        console.log("[SaasContent] Auto-jobs successfully sent to Watchdog.");
                    });
                }
            } catch (e) {
                console.debug("[SaasContent] Polling error:", e.message);
            }
        }, 15000);
    }

    // Auto-start 2 seconds after page load
    setTimeout(_startPolling, 2000);

    // ── CONTENT HOOK (notifies backend after job apply) ───────────────

    // 🌟 Added hr_name and hr_url parameters
    async function _notifyBackend(status, hr_name = null, hr_url = null) {
        try {
            const headers = await window.getAuthHeader();
            if (!headers["Authorization"]) return;

            let jobId = "unknown";
            
            // 🌟 THE FIX: Reliably capture BOTH types of LinkedIn URLs!
            const urlMatch = window.location.href.match(/\/jobs\/view\/(\d+)/) || 
                             window.location.href.match(/currentJobId=(\d+)/);
                             
            if (urlMatch) {
                jobId = urlMatch[1];
            } else {
                const activeJob = document.querySelector(".jobs-search-results-list__list-item--active");
                if (activeJob) {
                    jobId = activeJob.getAttribute("data-job-id") || "unknown";
                }
            }

            if (jobId === "unknown") {
                jobId = "auto_" + Date.now() + "_" + Math.floor(Math.random() * 1000);
            }

            const cleanUrl = jobId.startsWith("auto_") 
                ? window.location.href.split("?")[0] 
                : "https://www.linkedin.com/jobs/view/" + jobId + "/";

            // ... (keep the rest of your _notifyBackend title/company extraction exactly as is)

            const titleEl = document.querySelector(
                "h1.t-24, h2.t-24, " +
                ".jobs-unified-top-card__job-title, " +
                ".job-details-jobs-unified-top-card__job-title, " +
                ".top-card-layout__title"
            );
            let title = titleEl ? (titleEl.innerText || titleEl.textContent || "").trim().split("\n")[0] : null;
            if (!title || title === "") {
                title = document.title.split("|")[0].trim() || "Unknown Title";
            }

            const companySelectors = [
                ".job-details-jobs-unified-top-card__company-name",
                ".jobs-unified-top-card__company-name",
                ".jobs-unified-top-card__subtitle-primary-grouping a",
                "a[href*='/company/']", 
                "a.topcard__org-name-link"
            ].join(", ");

            let company = "Unknown Company";
            const topCard = document.querySelector(".job-details-jobs-unified-top-card, .jobs-unified-top-card, .job-view-layout") || document.body;
            const companyElements = topCard.querySelectorAll(companySelectors);
            
            for (let el of companyElements) {
                let text = (el.innerText || el.textContent || "").trim().split("\n")[0];
                if (text && text.length > 1 && !text.includes("Try Premium") && !text.includes("1-month free") && !text.includes("Save")) {
                    company = text;
                    break;
                }
            }

            await fetch(API + "/api/job-applied", {
                method: "POST",
                headers: Object.assign({ "Content-Type": "application/json" }, headers),
                body: JSON.stringify({
                    job_id:  jobId,
                    job_url: cleanUrl,
                    title:   title,
                    company: company,
                    status:  status,
                    hr_name: hr_name, // 🌟 Passing the targeted HR name
                    hr_url:  hr_url   // 🌟 Passing the targeted HR URL
                }),
            });
            console.log("[ContentHook] Stored:", status, "—", title, "@", company, "| HR:", hr_name);
        } catch (e) {
            console.debug("[ContentHook] notify failed:", e.message);
        }
    }

    // Message listener — relays from background.js and popup.js
    chrome.runtime.onMessage.addListener(function(request, sender, sendResponse) {

        if (request.action === "job_completed_notify") {
            // 🌟 Forward the HR data to the backend
            _notifyBackend(request.status, request.hr_name, request.hr_url);
            sendResponse({ status: "ok" });
            return false;
        }

        if (request.action === "start_auto_trigger") {
            var alreadyActive = _pollActive;
            _startPolling();
            sendResponse({ status: alreadyActive ? "already_running" : "started" });
            return false;
        }

        sendResponse({ status: "unknown_action" });
        return false;
    });

})(); // end IIFE