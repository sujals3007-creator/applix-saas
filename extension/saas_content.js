// saas_content.js
// ONE file that replaces: auth_manager.js + cookie_manager.js + content_hook.js + auto_trigger.js
// No load guards. No if-blocks. Direct window assignments throughout.
// All auth, cookie, hook and auto-trigger logic is here.
//
// FIX v4.1:
//   - _scanAndQueueJobs: reads targetLocations from chrome.storage instead of
//     hardcoding ["Mumbai", "Remote", "India"]. Locations are set by popup.js
//     fetchAndStorePrefs() when the user enables Auto Scan.
//   - Fallback is ["India"] (single entry, not a Mumbai-specific hardcode).

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
            const authHeaders = await window.getAuthHeader();
            const r = await fetch(API + "/api/save-cookies", {
                method: "POST",
                headers: { "Content-Type": "application/json", ...authHeaders },
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

    // ── AUTO-SCAN (runs directly in Chrome — no server-side requests, no IP blocks) ──────
    // This replaces the Python monitor.py scanner entirely for job discovery.
    // Since it runs inside Chrome with your logged-in session, LinkedIn never blocks it.

    let _scanActive = false;
    let _scanTimer  = null;
    const SCAN_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

    async function _autoScanEnabled() {
        const d = await new Promise(res => chrome.storage.local.get(["autoScanEnabled"], res));
        return !!d.autoScanEnabled;
    }

    async function _scanAndQueueJobs() {
        if (_scanActive) return;
        if (!(await _autoScanEnabled())) return;   // only when the user pressed "Start Auto Scan"
        _scanActive = true;

        try {
            const authHeaders = await window.getAuthHeader();
            if (!authHeaders["Authorization"]) { _scanActive = false; return; }

            // FIX: Read targetRoles AND targetLocations from chrome.storage.
            // popup.js fetchAndStorePrefs() saves both when Auto Scan is enabled.
            // This replaces the old hardcoded ["Mumbai", "Remote", "India"] list.
            const stored = await new Promise(res => chrome.storage.local.get(["targetRoles", "targetLocations"], res));
            let targetRoles     = stored.targetRoles     || null;
            let targetLocations = stored.targetLocations || null;

            // If not in storage yet, fetch from backend profile as fallback
            if (!targetRoles || !targetLocations) {
                try {
                    const profileResp = await fetch(API + "/api/profile", { headers: authHeaders });
                    if (profileResp.ok) {
                        const profileData = await profileResp.json();
                        const profile = profileData.profile || {};
                        if (!targetRoles && profile.target_roles) {
                            try { targetRoles = JSON.parse(profile.target_roles); } catch(e) {}
                        }
                        if (!targetLocations && profile.target_locations) {
                            try { targetLocations = JSON.parse(profile.target_locations); } catch(e) {}
                        }
                        // Cache in storage for next time
                        const updates = {};
                        if (targetRoles)     updates.targetRoles     = targetRoles;
                        if (targetLocations) updates.targetLocations = targetLocations;
                        if (Object.keys(updates).length > 0) {
                            chrome.storage.local.set(updates);
                        }
                    }
                } catch(e) {
                    console.warn("[AutoScan] Could not fetch profile prefs:", e.message);
                }
            }

            // Final fallbacks
            if (!targetRoles     || !targetRoles.length)     targetRoles     = ["AI Engineer"];
            if (!targetLocations || !targetLocations.length) targetLocations = ["India"];

            console.log(`[AutoScan] Roles: ${targetRoles.join(", ")} | Locations: ${targetLocations.join(", ")}`);

            const foundUrls = [];
            const seenJobIds = new Set();

            for (const role of targetRoles) {
                for (const location of targetLocations) {
                    try {
                        // f_AL=true = Easy Apply only; f_TPR=r86400 = last 24h; sortBy=DD = newest first
                        const keywords  = encodeURIComponent(`"${role}"`);
                        const loc       = encodeURIComponent(location);
                        const searchUrl = (
                            `https://www.linkedin.com/jobs/search/` +
                            `?keywords=${keywords}` +
                            `&location=${loc}` +
                            `&f_AL=true` +
                            `&f_TPR=r86400` +
                            `&sortBy=DD`
                        ); // 🌟 FIX: Removed slow refresh params

                        // Fetch the LinkedIn search page HTML directly from browser context
                        const r = await fetch(searchUrl, { credentials: "include" });
                        if (!r.ok) {
                            console.log(`[AutoScan] ${r.status} for role="${role}" location="${location}"`);
                            continue;
                        }

                        const html   = await r.text();
                        const parser = new DOMParser();
                        const doc    = parser.parseFromString(html, "text/html");

                        // 🌟 FIX: Extract job IDs directly from cards, as <a> tags are gone
                        const cards = doc.querySelectorAll("[data-job-id], .job-card-container, .job-card-list");
                        for (const card of cards) {
                            let jobId = card.getAttribute("data-job-id");
                            if (!jobId) {
                                const m = card.innerHTML.match(/\/jobs\/view\/(\d+)/) || card.innerHTML.match(/currentJobId=(\d+)/);
                                if (m) jobId = m[1];
                            }
                            if (!jobId || !/^\d+$/.test(jobId)) continue;
                            if (seenJobIds.has(jobId)) continue;

                            const titleEl = card.querySelector("[class*='title'], h3, h4");
                            const title = (titleEl?.textContent || card.textContent || "").trim().toLowerCase();
                            const roleWords = role.toLowerCase().split(" ");
                            if (!roleWords.every(w => title.includes(w))) continue;

                            seenJobIds.add(jobId);
                            foundUrls.push(`https://www.linkedin.com/jobs/view/${jobId}/`);
                        }

                        // Polite delay between searches
                        await new Promise(r => setTimeout(r, 3000));
                    } catch(e) {
                        console.log(`[AutoScan] Error for role="${role}" location="${location}":`, e.message);
                    }
                }
            }

            if (foundUrls.length > 0) {
                console.log(`[AutoScan] Found ${foundUrls.length} Easy Apply jobs — sending to queue`);
                chrome.runtime.sendMessage({ action: "start_campaign", urls: foundUrls });
            } else {
                console.log("[AutoScan] No new jobs found this cycle.");
            }

        } catch(e) {
            console.debug("[AutoScan] Scan error:", e.message);
        }

        _scanActive = false;
    }

    function _startAutoScan() {
        if (_scanTimer) return;
        console.log("[AutoScan] In-browser job scanner started.");
        setTimeout(_scanAndQueueJobs, 5000);
        _scanTimer = setInterval(_scanAndQueueJobs, SCAN_INTERVAL_MS);
    }

    // ── BACKEND POLLING (still polls for jobs queued by other means) ──────────────────

    let _pollTimer  = null;
    let _pollActive = false;

    function _startPolling() {
        if (_pollActive) return;
        _pollActive = true;

        _pollTimer = setInterval(async function() {
            if (!(await _autoScanEnabled())) return;
            // Route through background.js — content.js fetch to backend is CSP-blocked
            chrome.runtime.sendMessage({ action: "POLL_PENDING_JOBS" }, (data) => {
                if (!data) return;
                if (data.target_roles && data.target_roles.length > 0) {
                    chrome.storage.local.set({ targetRoles: data.target_roles });
                }
                if (data.jobs && data.jobs.length > 0) {
                    const urls = data.jobs.map(j => j.job_url || `https://www.linkedin.com/jobs/view/${j.job_id}/`);
                    chrome.runtime.sendMessage({ action: "start_campaign", urls }, () => {});
                }
            });
        }, 15000);
    }

    // Auto-start 2 seconds after page load
    setTimeout(async () => {
        if (await _autoScanEnabled()) { _startPolling(); _startAutoScan(); }
    }, 2000);

    async function _notifyBackend(status, hr_name = null, hr_url = null, match_score = 0) {
        try {
            const { token } = await window.getStoredToken();
            if (!token) return;

            let jobId = "unknown";
            const urlMatch = window.location.href.match(/\/jobs\/view\/(\d+)/) ||
                             window.location.href.match(/currentJobId=(\d+)/);
            if (urlMatch) {
                jobId = urlMatch[1];
            } else {
                const activeJob = document.querySelector(".jobs-search-results-list__list-item--active");
                if (activeJob) jobId = activeJob.getAttribute("data-job-id") || "unknown";
            }
            if (jobId === "unknown") jobId = "auto_" + Date.now() + "_" + Math.floor(Math.random() * 1000);

            const cleanUrl = jobId.startsWith("auto_")
                ? window.location.href.split("?")[0]
                : "https://www.linkedin.com/jobs/view/" + jobId + "/";

            const titleEl = document.querySelector(
                "h1.t-24, h2.t-24, .jobs-unified-top-card__job-title, " +
                ".job-details-jobs-unified-top-card__job-title, .top-card-layout__title"
            );
            let title = titleEl ? (titleEl.innerText || titleEl.textContent || "").trim().split("\n")[0] : null;
            if (!title || title === "") title = document.title.split("|")[0].trim() || "Unknown Title";

            const companySelectors = [
                ".job-details-jobs-unified-top-card__company-name",
                ".jobs-unified-top-card__company-name",
                ".jobs-unified-top-card__subtitle-primary-grouping a",
                "a[href*='/company/']",
                "a.topcard__org-name-link"
            ].join(", ");

            let company = "Unknown Company";
            const topCard = document.querySelector(".job-details-jobs-unified-top-card, .jobs-unified-top-card, .job-view-layout") || document.body;
            for (let el of topCard.querySelectorAll(companySelectors)) {
                let text = (el.innerText || el.textContent || "").trim().split("\n")[0];
                if (text && text.length > 1 && !text.includes("Try Premium") && !text.includes("1-month free") && !text.includes("Save")) {
                    company = text;
                    break;
                }
            }

            // Route through background.js — avoids LinkedIn's CSP blocking cross-origin fetch
            chrome.runtime.sendMessage({
                action:      "NOTIFY_JOB_APPLIED",
                job_id:      jobId,
                job_url:     cleanUrl,
                title:       title,
                company:     company,
                status:      status,
                hr_name:     hr_name,
                hr_url:      hr_url,
                match_score: match_score,
            });
            console.log("[ContentHook] Stored:", status, "—", title, "@", company, "| HR:", hr_name, "| Match:", match_score);
        } catch (e) {
            console.debug("[ContentHook] notify failed:", e.message);
        }
    }

    // Message listener — relays from background.js and popup.js
    chrome.runtime.onMessage.addListener(function(request, sender, sendResponse) {

        if (request.action === "job_completed_notify") {
            _notifyBackend(request.status, request.hr_name, request.hr_url, request.match_score);
            sendResponse({ status: "ok" });
            return false;
        }

        if (request.action === "start_auto_trigger") {
            var alreadyActive = _pollActive;
            _startPolling();
            _startAutoScan();
            sendResponse({ status: alreadyActive ? "already_running" : "started" });
            return false;
        }

        sendResponse({ status: "unknown_action" });
        return false;
    });

})(); // end IIFE