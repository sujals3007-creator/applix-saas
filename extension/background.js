// background.js - Autonomous Watchdog Edition

let isProcessingQueue = false;
let watchdogTimer = null;

chrome.runtime.onInstalled.addListener(() => {
    chrome.storage.local.set({ jobQueue: [], campaignTabId: null, lastTriggeredUrl: null });
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    
    if (request.action === "start_campaign" && request.urls) {
        chrome.storage.local.get(["jobQueue"], (data) => {
            let queue = data.jobQueue || [];
            queue.push(...request.urls);

            let tabId = sender.tab ? sender.tab.id : null;
            
            if (!tabId) {
                chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
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

    if (request.action === "job_completed") {
        console.log("Job finished naturally. Clearing watchdog...");
        clearTimeout(watchdogTimer); 
        
        if (sender.tab && sender.tab.id) {
            chrome.tabs.sendMessage(sender.tab.id, {
                action: "job_completed_notify",
                status: request.status,
                hr_name: request.hr_name, 
                hr_url: request.hr_url,
                match_score: request.match_score // 🌟 THE FIX: The score is finally relayed!
            }).catch(() => {});
        }
        
        isProcessingQueue = false;
        setTimeout(processNextJob, 2000);
        sendResponse({ status: "acknowledged" });
        return true;
    }

    if (request.action === "HARVEST_COOKIES") {
        chrome.cookies.get({ url: 'https://www.linkedin.com', name: 'li_at' }, (li_at_cookie) => {
            if (!li_at_cookie) { sendResponse({ success: false }); return; }
            
            chrome.cookies.get({ url: 'https://www.linkedin.com', name: 'JSESSIONID' }, (jsession_cookie) => {
                if (!jsession_cookie) { sendResponse({ success: false }); return; }
                
                let clean_jsession = jsession_cookie.value.replace(/"/g, '');

                fetch("https://ai-job-agent-backend-qmq1.onrender.com/api/save-cookies", {
                    method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ li_at: li_at_cookie.value, jsessionid: clean_jsession })
                })
                .then(r => r.json())
                .then(data => sendResponse({ success: true }))
                .catch(err => sendResponse({ success: false }));
            });
        });
        return true; 
    }
});

function startProcessing(queue, tabId) {
    chrome.storage.local.set({ jobQueue: queue, campaignTabId: tabId }, () => {
        if (!isProcessingQueue) processNextJob();
    });
}

function processNextJob() {
    clearTimeout(watchdogTimer); 
    
    chrome.storage.local.get(["jobQueue", "campaignTabId"], (data) => {
        let queue = data.jobQueue || [];
        let campaignTabId = data.campaignTabId;

        if (queue.length === 0) {
            isProcessingQueue = false;
            return;
        }

        isProcessingQueue = true;
        let nextUrl = queue.shift();
        chrome.storage.local.set({ jobQueue: queue });

        const match = nextUrl.match(/\/view\/(\d+)/);
        if (match) nextUrl = `https://www.linkedin.com/jobs/search/?currentJobId=${match[1]}&f_AL=true&refresh=${Date.now()}`;

        watchdogTimer = setTimeout(() => {
            console.warn("⏱️ Watchdog triggered! Tab froze. Auto-Skipping...");
            isProcessingQueue = false;
            processNextJob(); 
        }, 150000); 

        if (campaignTabId) {
            chrome.tabs.update(campaignTabId, { url: nextUrl, active: true }, () => {
                setTimeout(() => chrome.tabs.reload(campaignTabId), 1500);
            });
        } else {
            chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
                if (tabs.length > 0) {
                    chrome.storage.local.set({ campaignTabId: tabs[0].id });
                    chrome.tabs.update(tabs[0].id, { url: nextUrl, active: true }, () => {
                        setTimeout(() => chrome.tabs.reload(tabs[0].id), 1500);
                    });
                }
            });
        }
    });
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    chrome.storage.local.get(["campaignTabId", "lastTriggeredUrl"], (data) => {
        if (tabId === data.campaignTabId && changeInfo.status === "complete") {
            if (tab.url && tab.url.includes("currentJobId")) {
                if (data.lastTriggeredUrl === tab.url) return;
                chrome.storage.local.set({ lastTriggeredUrl: tab.url });
                
                setTimeout(() => {
                    chrome.tabs.sendMessage(tabId, { action: "auto_start_apply" })
                        .catch((err) => console.log("Tab still loading..."));
                }, 5000);
            }
        }
    });
});