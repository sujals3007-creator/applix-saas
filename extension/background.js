// background.js - Autonomous Watchdog + Auto Scan Edition
// FIX v4.1:
//   - buildSearchUrl: f_TPR extended to r86400 (24h) so more jobs appear
//   - scrapeSearchPage: now waits longer (5s) for React render, retries message
//   - processNextJob: navigates to /jobs/search/?currentJobId=X with f_AL=true
//     so the right pane ONLY shows Easy Apply jobs — non-EA jobs will have no
//     Easy Apply button and content.js will skip them cleanly
//   - Tab watcher: deduplication now uses full URL to prevent open/close loop
//   - runAutoScan: reads targetLocations from storage (set by popup.js fetchAndStorePrefs)
//     instead of falling back to a hardcoded list

const BACKEND_URL = "https://ai-job-agent-backend-qmq1.onrender.com";
const SCAN_INTERVAL_MINUTES = 5;

let isProcessingQueue = false;
let watchdogTimer = null;

// ─── Auto Scan state ──────────────────────────────────────────────
let scanTabId = null;       // The background tab used for scanning (never apply on this tab)
let isScanRunning = false;  // Lock: prevents overlapping scans

// ─────────────────────────────────────────────────────────────────
// INSTALL / INIT
// ─────────────────────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
    chrome.storage.local.set({
        jobQueue: [],
        campaignTabId: null,
        lastTriggeredUrl: null,
        autoScanEnabled: false,
    });
});

// ─────────────────────────────────────────────────────────────────
// ALARM: fires every SCAN_INTERVAL_MINUTES when auto scan is on
// ─────────────────────────────────────────────────────────────────
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === "autoScanAlarm") {
        runAutoScan();
    }
});

// ─────────────────────────────────────────────────────────────────
// MESSAGE LISTENER
// ─────────────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

    // ── Campaign: bulk queue from manual search page ──────────────
    if (request.action === "start_campaign" && request.urls) {
        chrome.storage.local.get(["jobQueue"], (data) => {
            let queue = data.jobQueue || [];
            queue.push(...request.urls);

            let tabId = sender.tab ? sender.tab.id : null;

            if (!tabId) {
                chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
                    if (tabs.length > 0) tabId = tabs[0].id;
                    startProcessing(queue, tabId);
                });
            } else {
                startProcessing(queue, tabId);
            }
        });
        sendResponse({ status: "started" });
        return true;
    }

    // ── Job finished naturally ────────────────────────────────────
    if (request.action === "job_completed") {
        console.log("Job finished naturally. Clearing watchdog...");
        clearTimeout(watchdogTimer);

        if (sender.tab && sender.tab.id) {
            chrome.tabs.sendMessage(sender.tab.id, {
                action: "job_completed_notify",
                status: request.status,
                hr_name: request.hr_name,
                hr_url: request.hr_url,
                match_score: request.match_score,
            }).catch(() => {});
        }

        isProcessingQueue = false;
        setTimeout(processNextJob, 8000); // 8s gap between jobs
        sendResponse({ status: "acknowledged" });
        return true;
    }

    // ── Backend proxy: Record a completed job application ─────────────────────────────
    if (request.action === "NOTIFY_JOB_APPLIED") {
        chrome.storage.local.get(["saas_jwt_token"], (tokenData) => {
            const headers = { "Content-Type": "application/json" };
            if (tokenData.saas_jwt_token) headers["Authorization"] = "Bearer " + tokenData.saas_jwt_token;
            fetch(`${BACKEND_URL}/api/job-applied`, {
                method:  "POST",
                headers: headers,
                body:    JSON.stringify({
                    job_id:      request.job_id,
                    job_url:     request.job_url,
                    title:       request.title,
                    company:     request.company,
                    status:      request.status,
                    hr_name:     request.hr_name,
                    hr_url:      request.hr_url,
                    match_score: request.match_score,
                }),
            })
                .then((r) => r.json())
                .then((data) => sendResponse({ ok: true, data }))
                .catch((err) => sendResponse({ ok: false, error: err.message }));
        });
        return true;
    }

    // ── Backend proxy: Poll for pending jobs queued via dashboard ─────────────────────
    if (request.action === "POLL_PENDING_JOBS") {
        chrome.storage.local.get(["saas_jwt_token"], (tokenData) => {
            if (!tokenData.saas_jwt_token) { sendResponse(null); return; }
            const headers = { "Authorization": "Bearer " + tokenData.saas_jwt_token };
            fetch(`${BACKEND_URL}/api/pending-jobs`, { headers })
                .then((r) => r.ok ? r.json() : null)
                .then((data) => sendResponse(data))
                .catch(() => sendResponse(null));
        });
        return true;
    }

    // ── Cookie sync ───────────────────────────────────────────────
    if (request.action === "WARMUP_BACKEND") {
        chrome.storage.local.get(["saas_jwt_token"], (tokenData) => {
            const headers = { "Content-Type": "application/json" };
            if (tokenData.saas_jwt_token) headers["Authorization"] = "Bearer " + tokenData.saas_jwt_token;
            fetch(`${BACKEND_URL}/api/agent/status`, { method: "GET", headers, signal: AbortSignal.timeout(8000) })
                .catch(() => {}) // fire-and-forget — just waking the server
                .finally(() => sendResponse({ ok: true }));
        });
        return true;
    }

    // ── Backend proxy: Fetch AI answers (called by content.js to avoid CSP blocks) ──
    // content.js runs inside LinkedIn's page and inherits its strict CSP, which
    // blocks cross-origin fetch to *.run.app. background.js is a service worker
    // with no page-level CSP, so all backend calls must be routed through here.
    if (request.action === "FETCH_AI_ANSWERS") {
        chrome.storage.local.get(["saas_jwt_token"], (tokenData) => {
            const headers = { "Content-Type": "application/json" };
            if (tokenData.saas_jwt_token) headers["Authorization"] = "Bearer " + tokenData.saas_jwt_token;

            const controller = new AbortController();
            const timeoutId  = setTimeout(() => controller.abort(), 48000); // 48s — Cloud Run cold start

            fetch(`${BACKEND_URL}/api/answer-questions`, {
                method:  "POST",
                headers: headers,
                signal:  controller.signal,
                body:    JSON.stringify({
                    questions:       request.questions,
                    job_description: request.job_description || "",
                }),
            })
                .then(async (r) => {
                    clearTimeout(timeoutId);
                    const text = await r.text();
                    if (!r.ok) {
                        // Backend returned 4xx/5xx — body is likely plain text like "Internal Server Error"
                        sendResponse({ status: "error", message: `HTTP ${r.status}: ${text.substring(0, 120)}` });
                        return;
                    }
                    try {
                        sendResponse(JSON.parse(text));
                    } catch (_) {
                        // Got 200 but body is not JSON (shouldn't happen, but handle gracefully)
                        sendResponse({ status: "error", message: `Non-JSON response: ${text.substring(0, 120)}` });
                    }
                })
                .catch((err) => { clearTimeout(timeoutId); sendResponse({ status: "error", message: err.message }); });
        });
        return true; // keep message channel open for async response
    }


    if (request.action === "HARVEST_COOKIES") {
        chrome.cookies.get({ url: "https://www.linkedin.com", name: "li_at" }, (li_at_cookie) => {
            if (!li_at_cookie) { sendResponse({ success: false }); return; }

            chrome.cookies.get({ url: "https://www.linkedin.com", name: "JSESSIONID" }, (jsession_cookie) => {
                if (!jsession_cookie) { sendResponse({ success: false }); return; }

                const clean_jsession = jsession_cookie.value.replace(/"/g, "");

                chrome.storage.local.get(["saas_jwt_token"], (tokenData) => {
                    const token = tokenData.saas_jwt_token || "";
                    const headers = { "Content-Type": "application/json" };
                    if (token) headers["Authorization"] = "Bearer " + token;

                    fetch(`${BACKEND_URL}/api/save-cookies`, {
                        method: "POST",
                        headers,
                        body: JSON.stringify({ li_at: li_at_cookie.value, jsessionid: clean_jsession }),
                    })
                        .then((r) => r.json())
                        .then(() => sendResponse({ success: true }))
                        .catch(() => sendResponse({ success: false }));
                });
            });
        });
        return true;
    }

    // ── Auto Scan: START ──────────────────────────────────────────
    if (request.action === "START_AUTO_SCAN") {
        chrome.storage.local.set({ autoScanEnabled: true }, () => {
            chrome.alarms.create("autoScanAlarm", {
                delayInMinutes: 0,
                periodInMinutes: SCAN_INTERVAL_MINUTES,
            });
            console.log(`[AutoScan] Started. Interval: ${SCAN_INTERVAL_MINUTES} mins.`);
            sendResponse({ success: true });
        });
        return true;
    }

    // ── Auto Scan: STOP ───────────────────────────────────────────
    if (request.action === "STOP_AUTO_SCAN") {
        chrome.storage.local.set({ autoScanEnabled: false }, () => {
            chrome.alarms.clear("autoScanAlarm", () => {
                if (scanTabId) {
                    chrome.tabs.remove(scanTabId).catch(() => {});
                    scanTabId = null;
                }
                isScanRunning = false;
                console.log("[AutoScan] Stopped.");
                sendResponse({ success: true });
            });
        });
        return true;
    }
});

// ─────────────────────────────────────────────────────────────────
// AUTO SCAN ENGINE
// ─────────────────────────────────────────────────────────────────

async function runAutoScan() {
    if (isScanRunning) {
        console.log("[AutoScan] Already running — skipping this tick.");
        return;
    }
    isScanRunning = true;
    console.log("[AutoScan] Scan started.");

    try {
        const data = await storageGet(["targetRoles", "targetLocations", "saas_jwt_token", "autoScanEnabled", "jobQueue"]);

        if (!data.autoScanEnabled) {
            isScanRunning = false;
            return;
        }

        if (!isProcessingQueue) {
            await new Promise((r) => chrome.storage.local.remove(["campaignSearchQuery", "manualCampaignRole", "manualCampaignLocation"], r));
        }
        const roles     = data.targetRoles     || ["AI Engineer"];
        // FIX: read targetLocations from storage (set by popup.js fetchAndStorePrefs)
        // instead of falling back to a hardcoded list
        const locations = (data.targetLocations && data.targetLocations.length > 0)
            ? data.targetLocations
            : ["India"];
        const token         = data.saas_jwt_token  || "";
        const existingQueue = data.jobQueue        || [];

        console.log(`[AutoScan] Roles: ${roles.join(", ")} | Locations: ${locations.join(", ")}`);

        // Build a set of job IDs already in queue (avoid re-adding)
        const existingQueueIds = new Set(
            existingQueue
                .map((u) => (u.match(/\/view\/(\d+)/) || [])[1])
                .filter(Boolean)
        );

        // Fetch already-applied job IDs from backend to skip those too
        const appliedIds = await fetchAppliedJobIds(token);

        const allNewJobUrls = [];

        for (const role of roles) {
            for (const location of locations) {
                // FIX: buildSearchUrl now uses f_TPR=r86400 (24h window) so enough
                // jobs appear; f_AL=true ensures only Easy Apply jobs are listed.
                const url    = buildSearchUrl(role, location);
                const jobIds = await scrapeSearchPage(url);
                console.log(`[AutoScan] role="${role}" location="${location}" → ${jobIds.length} Easy Apply jobs found`);

                for (const id of jobIds) {
                    if (!existingQueueIds.has(id) && !appliedIds.has(id)) {
                        allNewJobUrls.push(`https://www.linkedin.com/jobs/view/${id}/`);
                        existingQueueIds.add(id);
                    }
                }

                if (roles.length * locations.length > 1) {
                    await sleep(3000);
                }
            }
        }

        if (allNewJobUrls.length === 0) {
            console.log("[AutoScan] No new jobs found this tick.");
            isScanRunning = false;
            return;
        }

        console.log(`[AutoScan] Adding ${allNewJobUrls.length} new jobs to queue.`);

        const updatedQueue = [...existingQueue, ...allNewJobUrls];
        await storageSet({ jobQueue: updatedQueue });

        if (!isProcessingQueue) {
            processNextJob();
        }

    } catch (err) {
        console.error("[AutoScan] Error:", err);
    }

    isScanRunning = false;
}

/**
 * Build a LinkedIn Easy Apply search URL.
 * FIX: f_TPR=r86400 (24h) gives a bigger pool of results than r3600 (1h).
 * f_AL=true = Easy Apply only. sortBy=DD = most recent first.
 */
function buildSearchUrl(role, location) {
    const encodedRole = encodeURIComponent(`"${role}"`);
    const encodedLoc  = encodeURIComponent(location);
    return (
        `https://www.linkedin.com/jobs/search-results/` +
        `?keywords=${encodedRole}` +
        `&location=${encodedLoc}` +
        `&f_AL=true` +        
        `&f_TPR=r86400` +     
        `&sortBy=DD`
    ); // 🌟 FIX: Removed slow refresh params
}

/**
 * Opens a SILENT background tab, waits for page load,
 * asks content.js to scrape job IDs from the Easy Apply listing,
 * then closes the tab.
 *
 * FIX: increased React render wait from 3s → 5s; added message retry
 * logic so we don't silently return [] if content.js isn't ready yet.
 */
function scrapeSearchPage(url) {
    return new Promise((resolve) => {
        let resolved = false;

        const hardTimeout = setTimeout(() => {
            if (!resolved) {
                resolved = true;
                console.warn("[AutoScan] Scan tab timed out:", url);
                if (scanTabId) {
                    chrome.tabs.remove(scanTabId).catch(() => {});
                    scanTabId = null;
                }
                resolve([]);
            }
        }, 45000); // FIX: 45s hard timeout (was 30s)

        chrome.tabs.create({ url, active: false }, (tab) => {
            scanTabId = tab.id;

            function onUpdated(tabId, changeInfo) {
                if (tabId !== tab.id || changeInfo.status !== "complete") return;
                chrome.tabs.onUpdated.removeListener(onUpdated);

                // FIX: Wait 5s for LinkedIn React to render job cards (was 3s)
                // Then retry the message up to 3 times with 2s gaps in case
                // the content script hasn't fully initialised yet.
                let attempts = 0;
                function tryScrape() {
                    attempts++;
                    chrome.tabs.sendMessage(tab.id, { action: "SCRAPE_JOBS_FOR_SCAN" }, (jobIds) => {
                        if (chrome.runtime.lastError) {
                            // Content script not ready yet
                            if (attempts < 3 && !resolved) {
                                setTimeout(tryScrape, 2000);
                            } else if (!resolved) {
                                resolved = true;
                                clearTimeout(hardTimeout);
                                chrome.tabs.remove(tab.id).catch(() => {});
                                scanTabId = null;
                                resolve([]);
                            }
                            return;
                        }
                        if (!resolved) {
                            resolved = true;
                            clearTimeout(hardTimeout);
                            chrome.tabs.remove(tab.id).catch(() => {});
                            scanTabId = null;
                            resolve(Array.isArray(jobIds) ? jobIds : []);
                        }
                    });
                }

                setTimeout(tryScrape, 5000);
            }

            chrome.tabs.onUpdated.addListener(onUpdated);
        });
    });
}

/** Fetch job IDs the user already applied to — so we don't re-queue them */
async function fetchAppliedJobIds(token) {
    const ids = new Set();
    if (!token) return ids;
    try {
        const resp = await fetch(`${BACKEND_URL}/api/dashboard/jobs`, {
            headers: { Authorization: "Bearer " + token },
        });
        if (resp.ok) {
            const data = await resp.json();
            (data.jobs || []).forEach((j) => {
                if (j.job_url) {
                    const m = j.job_url.match(/\/view\/(\d+)/);
                    if (m) ids.add(m[1]);
                }
            });
        }
    } catch (e) {
        console.warn("[AutoScan] Could not fetch applied jobs:", e);
    }
    return ids;
}

/**
 * Build the URL used to open ONE job inside LinkedIn's current search UI
 * (/jobs/search-results/ — the old /jobs/search/ path is no longer the real page and
 * redirecting between the two caused loops). If the user started the campaign from a
 * filtered search, we keep those filters (Easy Apply, past 24h, ...) and only swap currentJobId.
 */
function buildJobUrl(jobId, savedQuery, keywordsParam, locationParam) {
    const base = "https://www.linkedin.com/jobs/search-results/";
    if (savedQuery) {
        try {
            const qs = new URLSearchParams(savedQuery.startsWith("?") ? savedQuery : "?" + savedQuery);
            ["eBP", "refId", "trackingId", "referralSearchId", "origin", "start"].forEach((k) => qs.delete(k));
            qs.set("currentJobId", jobId);
            qs.set("f_AL", "true");
            return base + "?" + qs.toString();
        } catch (e) { /* fall through */ }
    }
    return `${base}?currentJobId=${jobId}&f_AL=true&keywords=${keywordsParam}&location=${locationParam}`;
}

// ─────────────────────────────────────────────────────────────────
// CAMPAIGN PROCESSING
// ─────────────────────────────────────────────────────────────────

function startProcessing(queue, tabId) {
    chrome.storage.local.set({ jobQueue: queue, campaignTabId: tabId }, () => {
        if (!isProcessingQueue) processNextJob();
    });
}

function processNextJob() {
    clearTimeout(watchdogTimer);

    chrome.storage.local.get(["jobQueue", "campaignTabId", "targetRoles", "targetLocations", "manualCampaignRole", "manualCampaignLocation", "campaignSearchQuery"], (data) => {
        const queue         = data.jobQueue      || [];
        const campaignTabId = data.campaignTabId;
        // 🌟 FIX: Check for manual override from popup.js first
        const roles         = data.targetRoles   || ["AI Engineer"];
        const locations     = data.targetLocations || ["India"];
        
        let keywordsParam = "";
        let locationParam = "";

        if (data.manualCampaignRole) {
            keywordsParam = encodeURIComponent(data.manualCampaignRole);
            locationParam = encodeURIComponent(data.manualCampaignLocation || locations[0] || "India");
        } else {
            keywordsParam = encodeURIComponent(roles[0] || "AI Engineer");
            locationParam = encodeURIComponent(locations[0] || "India");
        }

        if (queue.length === 0) {
            isProcessingQueue = false;
            console.log("[Campaign] Queue empty. Waiting for next scan.");
            return;
        }

        isProcessingQueue = true;
        const rawUrl = queue.shift();
        chrome.storage.local.set({ jobQueue: queue });

        // FIX: Rebuild as /jobs/search/?currentJobId=X with:
        //   - f_AL=true  → right pane only shows Easy Apply jobs
        //   - keywords   → keeps search context for the left pane
        //   - location   → keeps geo context
        // This means if a job somehow ends up in the queue without Easy Apply,
        // the button simply won't exist and content.js will skip it cleanly.
        const match = rawUrl.match(/\/view\/(\d+)|currentJobId=(\d+)/);
        let nextUrl = rawUrl;
        if (match) {
            const jobId = match[1] || match[2];
            nextUrl = buildJobUrl(jobId, data.campaignSearchQuery, keywordsParam, locationParam);
        }

        // Reset the duplicate-trigger guard so this job is ALWAYS allowed to fire once.
        // (Previously a stale lastTriggeredJobId could silently block a job and hang the queue.)
        chrome.storage.local.set({ lastTriggeredJobId: null });

        console.log(`[Campaign] Loading job: ${nextUrl}`);

        // Watchdog: skip frozen tabs after 2.5 mins
        watchdogTimer = setTimeout(() => {
            console.warn("⏱️ Watchdog triggered! Tab froze. Auto-Skipping...");
            isProcessingQueue = false;
            processNextJob();
        }, 150000);

        if (campaignTabId) {
            chrome.tabs.update(campaignTabId, { url: nextUrl, active: true });
        } else {
            chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
                if (tabs.length > 0) {
                    const tabId = tabs[0].id;
                    
                    // FIX: Wait for storage to finish saving before triggering navigation
                    chrome.storage.local.set({ campaignTabId: tabId }, () => {
                        chrome.tabs.update(tabId, { url: nextUrl, active: true });
                    });
                }
            });
        }
    });
}

// ─────────────────────────────────────────────────────────────────
// TAB WATCHER — triggers apply on campaign tab only
//
// FIX: deduplication now uses the full reconstructed URL (jobId + keywords)
// rather than just jobId. Previously, re-navigating to the same jobId on a
// fresh tab would be blocked by the dedupe check, causing the
// "open → close → reopen same page" loop.
// New logic: track lastTriggeredJobId separately and reset it when the queue
// advances, so each job triggers exactly once.
// ─────────────────────────────────────────────────────────────────
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    // 🌟 FIX: Removed the "complete" check! 
    // LinkedIn tracking pixels often hang the tab loader. We bypass the browser 
    // status and rely entirely on our DOM poller to know when the page is ready.
    if (!tab.url) return;

    // Never trigger apply on the background scan tab
    if (tabId === scanTabId) return;

    const jobMatch = tab.url.match(/currentJobId=(\d+)/) || tab.url.match(/\/jobs\/view\/(\d+)/);
    if (!jobMatch) return;
    const jobId = jobMatch[1];

    chrome.storage.local.get(["campaignTabId", "lastTriggeredJobId"], (data) => {
        if (tabId !== data.campaignTabId) return;

        // FIX: deduplicate on jobId — but ONLY skip if this exact jobId already
        // fired. We store it as lastTriggeredJobId. processNextJob() shifts the
        // queue before navigation so a new jobId always comes through.
        if (data.lastTriggeredJobId === jobId) {
            console.log(`[TabWatcher] Already triggered jobId=${jobId}, skipping duplicate event.`);
            return;
        }
        chrome.storage.local.set({ lastTriggeredJobId: jobId });

        // BUG FIX: LinkedIn is a SPA — "complete" fires before the job detail
        // pane has rendered. Instead of a fixed 2s delay, we poll via scripting
        // until the Easy Apply button (or a known detail-pane element) appears,
        // then fire the agent. Max wait: 30s before giving up.
        let _pollAttempt = 0;
        const MAX_POLL   = 20;   // 20 × 1500ms = 30s max
        const POLL_MS    = 1500;

        function _pollForReadiness() {
            _pollAttempt++;
            chrome.scripting.executeScript(
                {
                    target: { tabId },
                    func: () => {
                        const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
                        // Real Easy Apply button of the right pane (never a job card / filter pill)
                        const hasEasyApply = Array.from(document.querySelectorAll('button[aria-label*="Easy Apply" i], a[aria-label*="Easy Apply" i]'))
                            .some(b => visible(b) && !b.closest('[componentkey^="job-card-component-ref-"]'));
                        // Detail pane rendered but job has no Easy Apply (external apply / already applied)
                        const hasDetailPane = !!document.querySelector('[componentkey^="JobMatchRef_"], [componentkey^="JobDetailsPage_"], .job-details-jobs-unified-top-card__job-title, .jobs-apply-button')
                            || Array.from(document.querySelectorAll("button")).some(b => visible(b) && /^(save|saved)$/i.test((b.innerText || "").trim()));
                        return hasEasyApply || hasDetailPane;
                    },
                },
                (results) => {
                    const isReady = results && results[0] && results[0].result;
                    if (isReady) {
                        console.log(`[TabWatcher] Detail pane ready after ${_pollAttempt} polls. Firing agent.`);
                        _fireAgent();
                    } else if (_pollAttempt < MAX_POLL) {
                        setTimeout(_pollForReadiness, POLL_MS);
                    } else {
                        console.warn(`[TabWatcher] Detail pane never loaded for jobId=${jobId}. Skipping.`);
                        clearTimeout(watchdogTimer);
                        isProcessingQueue = false;
                        setTimeout(processNextJob, 3000);
                    }
                }
            );
        }

        // Small head-start so the SPA has time to begin rendering
        setTimeout(_pollForReadiness, 1500);

        let _fireAttempt = 0;
        function _fireAgent() {
            _fireAttempt++;
            chrome.tabs.sendMessage(tabId, { action: "auto_start_apply" }, (resp) => {
                if (chrome.runtime.lastError || !resp) {
                    if (_fireAttempt < 8) {
                        setTimeout(_fireAgent, 1500);
                    } else {
                        console.log("[Watchdog] Content script not responding after 12s — skipping.");
                        clearTimeout(watchdogTimer);
                        isProcessingQueue = false;
                        setTimeout(processNextJob, 3000);
                    }
                }
            });
        }
    });
});

// ─────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────
function storageGet(keys) {
    return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
}

function storageSet(obj) {
    return new Promise((resolve) => chrome.storage.local.set(obj, resolve));
}

function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
}