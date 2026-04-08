// popup.js - Minimalist Edition
"use strict";

document.getElementById('startCampaignBtn').addEventListener('click', async () => {
    const st = document.getElementById('status');
    st.innerText = "🔍 Finding LinkedIn Jobs tab..."; 
    st.style.color = "#0a66c2";

    let allTabs = await chrome.tabs.query({ url: "*://www.linkedin.com/jobs/*" });
    if (!allTabs.length) allTabs = await chrome.tabs.query({ url: "*://www.linkedin.com/*" });
    const tab = allTabs.find(t => t.url && t.url.includes("linkedin.com/jobs"));

    if (!tab) {
        st.innerText = "❌ Open a LinkedIn Jobs Search page first.";
        st.style.color = "red";
        return;
    }

    st.innerText = "⏳ Sending campaign start signal...";
    chrome.tabs.sendMessage(tab.id, { action: "start_same_tab_campaign" }, (resp) => {
        if (chrome.runtime.lastError || !resp) {
            st.innerText = "⚠️ Refresh the LinkedIn page then click again.";
            st.style.color = "#b45309";
            return;
        }
        st.innerText = "🚀 Campaign running! Watch the LinkedIn tab.";
        st.style.color = "green";
        document.getElementById('startCampaignBtn').innerText = "⏳ Running...";
        setTimeout(() => window.close(), 1500);
    });
});

document.getElementById('syncCookiesBtn').addEventListener('click', () => {
    const statusText = document.getElementById('status');
    statusText.innerText = "⏳ Extracting credentials...";
    statusText.style.color = "#0a66c2";

    chrome.runtime.sendMessage({ action: "HARVEST_COOKIES" }, (response) => {
        if (response && response.success) {
            statusText.innerText = "✅ Connection Synced!";
            statusText.style.color = "green";
        } else {
            statusText.innerText = "❌ Please log into LinkedIn first.";
            statusText.style.color = "red";
        }
    });
});