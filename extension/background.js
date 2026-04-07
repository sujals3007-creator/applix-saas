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