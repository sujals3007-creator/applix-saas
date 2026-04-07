// background.js - Autonomous Watchdog Edition

let isProcessingQueue = false;
let activeCampaignTabId = null;
let lastTriggeredUrl = null;
let watchdogTimer = null; // 🌟 NEW: The Self-Healing Watchdog

chrome.storage.local.remove("isProcessingQueue");

chrome.runtime.onInstalled.addListener(() => {
    chrome.storage.local.set({ jobQueue: [] });
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "start_campaign" && request.urls) {
        chrome.storage.local.get(["jobQueue"], (data) => {
            let queue = data.jobQueue || [];
            queue.push(...request.urls);

            if (sender.tab && sender.tab.id) activeCampaignTabId = sender.tab.id;

            chrome.storage.local.set({ jobQueue: queue, campaignTabId: activeCampaignTabId }, () => {
                if (!isProcessingQueue) processNextJob();
            });
        });
        sendResponse({ status: "started" });
        return true;
    }

    if (request.action === "job_completed") {
        console.log("Job finished naturally. Clearing watchdog...");
        clearTimeout(watchdogTimer); 
        
        if (sender.tab && sender.tab.id) {
            chrome.tabs.sendMessage(sender.tab.id, {
                action: "job_completed_notify",
                status: request.status,
                hr_name: request.hr_name, // 🌟 NEW
                hr_url: request.hr_url    // 🌟 NEW
            });
        }
        
        isProcessingQueue = false;
        setTimeout(processNextJob, 2000);
        sendResponse({ status: "acknowledged" });
        return true;
    }
});

function processNextJob() {
    clearTimeout(watchdogTimer); // Reset watchdog
    
    chrome.storage.local.get(["jobQueue", "campaignTabId"], (data) => {
        let queue = data.jobQueue || [];
        activeCampaignTabId = data.campaignTabId || activeCampaignTabId;

        if (queue.length === 0) {
            isProcessingQueue = false;
            return;
        }

        isProcessingQueue = true;
        let nextUrl = queue.shift();
        chrome.storage.local.set({ jobQueue: queue });

        const match = nextUrl.match(/\/view\/(\d+)/);
        if (match) nextUrl = `https://www.linkedin.com/jobs/search/?currentJobId=${match[1]}&f_AL=true&refresh=${Date.now()}`;

        // 🌟 START THE WATCHDOG TIMER (2.5 Minutes)
        // If the tab freezes because you Alt-Tabbed, this will forcefully fix it!
        watchdogTimer = setTimeout(() => {
            console.warn("⚠️ Watchdog triggered! Tab froze or took too long. Auto-Skipping...");
            isProcessingQueue = false;
            processNextJob(); // Force move to next job
        }, 150000); 

        chrome.tabs.update(activeCampaignTabId, { url: nextUrl, active: true }, () => {
            setTimeout(() => chrome.tabs.reload(activeCampaignTabId), 1500);
        });
    });
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (tabId === activeCampaignTabId && changeInfo.status === "complete") {
        if (tab.url && tab.url.includes("currentJobId")) {
            if (lastTriggeredUrl === tab.url) return;
            lastTriggeredUrl = tab.url;
            
            // 🌟 THE FIX: Added .catch() so Chrome ignores the harmless loading error!
            setTimeout(() => {
                chrome.tabs.sendMessage(tabId, { action: "auto_start_apply" })
                    .catch((err) => console.log("Tab still loading, ignoring warning..."));
            }, 5000);
        }
    }
});
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "HARVEST_COOKIES") {
        
        // Grab the li_at cookie
        chrome.cookies.get({ url: 'https://www.linkedin.com', name: 'li_at' }, (li_at_cookie) => {
            if (!li_at_cookie) { sendResponse({ success: false }); return; }
            
            // Grab the JSESSIONID cookie
            chrome.cookies.get({ url: 'https://www.linkedin.com', name: 'JSESSIONID' }, (jsession_cookie) => {
                if (!jsession_cookie) { sendResponse({ success: false }); return; }
                
                // Format JSESSIONID properly (sometimes it has quotes around it)
                let clean_jsession = jsession_cookie.value.replace(/"/g, '');

                // Beam to the Render Backend
                fetch("https://ai-job-agent-backend-qmq1.onrender.com/api/save-cookies", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    // In the future, we will send an Auth token here to attach these cookies to the specific candidate's DB row
                    body: JSON.stringify({ 
                        li_at: li_at_cookie.value, 
                        jsessionid: clean_jsession 
                    })
                })
                .then(r => r.json())
                .then(data => sendResponse({ success: true }))
                .catch(err => sendResponse({ success: false }));
            });
        });
        return true; // Keeps the message channel open for async response
    }
});