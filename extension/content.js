// content.js — AI Job Agent v9 (Aggressive Popup Killer Edition)

console.log("🤖 AI Job Agent content.js loaded.");

// ─────────────────────────────────────────────────────────────────
// UI: THE AGENT CONSOLE PANEL
// ─────────────────────────────────────────────────────────────────
const panel = document.createElement("div");
panel.id = "ai-agent-panel";
panel.style.cssText = `
    position: fixed; bottom: 20px; right: 20px; width: 420px; height: 400px;
    background: rgba(15, 23, 42, 0.95); color: #e2e8f0;
    font-family: 'Courier New', Courier, monospace; font-size: 11px;
    z-index: 999999; border: 1px solid #334155; border-radius: 8px;
    display: flex; flex-direction: column; box-shadow: 0 10px 25px rgba(0,0,0,0.5);
    backdrop-filter: blur(4px);
`;

const header = document.createElement("div");
header.style.cssText = `
    background: #1e293b; padding: 10px 15px; font-weight: bold;
    border-radius: 8px 8px 0 0; display: flex; justify-content: space-between; align-items: center;
    border-bottom: 1px solid #334155; font-size: 13px;
`;
header.innerHTML = `
    <span style="display:flex; align-items:center; gap:8px;">
        <span id="ai-agent-indicator" style="width:10px;height:10px;border-radius:50%;background:#ef4444;"></span>
        🤖 AI Agent Telemetry
    </span>
    <button id="ai-copy-btn" style="background:#0a66c2;color:white;border:none;border-radius:4px;cursor:pointer;font-size:11px;padding:4px 8px;font-weight:bold;">Copy Logs</button>
`;

const logContainer = document.createElement("div");
logContainer.style.cssText = "flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 6px;";

panel.appendChild(header);
panel.appendChild(logContainer);
document.body.appendChild(panel);

document.getElementById("ai-copy-btn").addEventListener("click", () => {
    navigator.clipboard.writeText(logContainer.innerText);
    const btn = document.getElementById("ai-copy-btn");
    btn.innerText = "Copied!";
    btn.style.background = "#10b981";
    setTimeout(() => { btn.innerText = "Copy Logs"; btn.style.background = "#0a66c2"; }, 2000);
});

function agentLog(msg, color = "#94a3b8") {
    const time = new Date().toLocaleTimeString("en-US", { hour12: false });
    const line = document.createElement("div");
    line.style.color = color;
    line.style.wordWrap = "break-word";
    line.style.lineHeight = "1.4";
    line.innerText = `[${time}] ${msg}`;
    logContainer.appendChild(line);
    logContainer.scrollTop = logContainer.scrollHeight;
    console.log(`[Agent] ${msg}`);
}

function setAgentStatus(status) {
    const dot = document.getElementById("ai-agent-indicator");
    if (status === "running") dot.style.background = "#10b981"; 
    else if (status === "error") dot.style.background = "#ef4444"; 
    else dot.style.background = "#eab308"; 
}

// ─────────────────────────────────────────────────────────────────
// UTILITIES
// ─────────────────────────────────────────────────────────────────
let _jobStatus = "idle"; 
let _campaignRunning = false;
let _foundHrName = null;
let _foundHrUrl = null;

const humanDelay = (min = 1500, max = 3000) => new Promise(r => setTimeout(r, Math.floor(Math.random() * (max - min + 1)) + min));

const humanScroll = async () => {
    window.scrollBy({ top: 400, behavior: "smooth" });
    await humanDelay(1000, 2500);
    window.scrollBy({ top: -200, behavior: "smooth" });
    await humanDelay(800, 1500);
};

function deepQuerySelectorAll(selector, root = document) {
    let els = Array.from(root.querySelectorAll(selector));
    for (const node of root.querySelectorAll("*")) {
        if (node.shadowRoot) els = els.concat(deepQuerySelectorAll(selector, node.shadowRoot));
    }
    return els;
}

function getActiveModal() {
    const modals = deepQuerySelectorAll(".jobs-easy-apply-modal, .artdeco-modal, [role='dialog']");
    return modals.find(m => m.getBoundingClientRect().width > 100 && window.getComputedStyle(m).display !== "none" && m.querySelector("button, input")) || document.body;
}

// ─────────────────────────────────────────────────────────────────
// MODAL KILLER & ABORT MECHANISM (UPGRADED)
// ─────────────────────────────────────────────────────────────────
async function _dismissBlockingModals() {
    await humanDelay(800, 1200);
    
    const activeModals = deepQuerySelectorAll(".jobs-easy-apply-modal, .artdeco-modal, [role='dialog']").filter(m => m.getBoundingClientRect().width > 0 && window.getComputedStyle(m).display !== "none");
    
    // 🌟 CRITICAL FIX: If no modal is open, stop immediately!
    // This prevents the agent from accidentally clicking the "Dismiss Job" 'X' icons on the left panel.
    if (activeModals.length === 0) return;
    
    const searchRoot = activeModals[0];

    const allBtns = deepQuerySelectorAll("button", searchRoot).filter(b => b.getBoundingClientRect().width > 0);
    const dismissBtn = allBtns.find(b => {
        const t = (b.innerText || "").toLowerCase().trim();
        return ["done", "return to job search", "continue applying", "got it", "no thanks", "dismiss", "close", "leave", "discard"].includes(t);
    });

    if (dismissBtn) {
        agentLog(`[Debug] Clicking text popup button: "${dismissBtn.innerText.trim()}"`, "#d946ef");
        dismissBtn.click();
        await humanDelay(1000, 1500);
        return;
    }

    const closeSelectors = [".artdeco-modal__dismiss", "button[aria-label='Dismiss']", "button[aria-label='Close']", "button[data-control-name='post_apply_modal_dismiss']"];
    for (const sel of closeSelectors) {
        const btn = deepQuerySelectorAll(sel, searchRoot)[0];
        if (btn && btn.getBoundingClientRect().width > 0) { 
            agentLog(`[Debug] Clicking popup 'X' icon`, "#d946ef");
            btn.click(); 
            await humanDelay(1000, 1500); 
            return; 
        }
    }
}

async function _abortCurrentApplication() {
    agentLog("⚠️ Aborting application to clear screen...", "#fbbf24");
    const closeBtn = document.querySelector("button[aria-label='Dismiss'], button[aria-label='Close'], .artdeco-modal__dismiss");
    if (closeBtn && closeBtn.getBoundingClientRect().width > 0) {
        closeBtn.click();
        await humanDelay(1000, 1500);
    }
    const discardBtn = Array.from(document.querySelectorAll("button")).find(b => (b.innerText || "").toLowerCase().includes("discard") && b.getBoundingClientRect().width > 0);
    if (discardBtn) {
        discardBtn.click();
        await humanDelay(1000, 1500);
    }
    await _dismissBlockingModals();
}

// ─────────────────────────────────────────────────────────────────
// REACT FORM FILLER
// ─────────────────────────────────────────────────────────────────
async function setReactValue(element, value) {
    try {
        if (element.tagName.toLowerCase() === "fieldset") {
            const search = String(value).toLowerCase().trim();
            const radios = Array.from(element.querySelectorAll("input[type='radio'], input[type='checkbox']"));
            let matched = radios.find(r => {
                const labelText = (r.nextElementSibling?.innerText || r.parentElement?.innerText || "").toLowerCase();
                return labelText.includes(search) || (r.value || "").toLowerCase().includes(search);
            });
            if (!matched && radios.length > 0) {
                if (search.includes("yes") || search === "1" || search === "true") matched = radios.find(r => (r.nextElementSibling?.innerText || "").toLowerCase().includes("yes"));
                if (!matched) matched = radios[0]; 
            }
            if (matched) { matched.click(); matched.dispatchEvent(new Event("change", { bubbles: true })); }
            return;
        }

        const tag = element.tagName.toLowerCase();

        // 🌟 NEW: Handles standalone mandatory checkboxes (e.g. "I agree to the terms")
        if (tag === "input" && (element.type === "checkbox" || element.type === "radio")) {
            const search = String(value).toLowerCase().trim();
            const isPositive = search === "yes" || search === "true" || search === "1" || search === "agree" || search === "accept" || search === "data not found";
            if (isPositive && !element.checked) {
                element.click();
                element.dispatchEvent(new Event("change", { bubbles: true }));
            }
            return;
        }

        element.focus();
        element.dispatchEvent(new Event("focus", { bubbles: true }));

        if (tag === "select") {
            const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value").set;
            const search = String(value).toLowerCase().trim();
            let opt = Array.from(element.options).find(o => o.value.toLowerCase().includes(search) || o.text.toLowerCase().includes(search));
            if (!opt && element.options.length > 1) opt = element.options[1]?.value !== "" ? element.options[1] : element.options[element.options.length - 1];
            if (opt) {
                if (setter) setter.call(element, opt.value); else element.value = opt.value;
                element.dispatchEvent(new Event("change", { bubbles: true }));
            }
            return;
        }

        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
        if (setter) setter.call(element, ""); else element.value = "";
        element.dispatchEvent(new Event("input", { bubbles: true }));

        let current = "";
        for (const ch of String(value)) {
            current += ch;
            if (setter) setter.call(element, current); else element.value = current;
            element.dispatchEvent(new Event("input", { bubbles: true }));
            element.dispatchEvent(new KeyboardEvent("keydown", { key: ch, bubbles: true }));
            element.dispatchEvent(new KeyboardEvent("keyup", { key: ch, bubbles: true }));
            await new Promise(r => setTimeout(r, 40));
        }
        element.dispatchEvent(new Event("change", { bubbles: true }));
        
        if (element.getAttribute("role") === "combobox" || element.id.toLowerCase().includes("location") || element.id.toLowerCase().includes("city")) {
            agentLog(`[Debug] Combobox detected. Waiting for LinkedIn dropdown...`, "#d946ef");
            await new Promise(r => setTimeout(r, 2000)); 
            const container = element.closest('.jobs-easy-apply-form-section__grouping') || document.body;
            const dropdown = container.querySelector("[role='listbox'], .basic-typeahead__results");
            if (dropdown) {
                const options = dropdown.querySelectorAll("[role='option'], .basic-typeahead__result");
                if (options.length > 0) {
                    const firstOption = options[0];
                    firstOption.scrollIntoView({ behavior: "smooth", block: "nearest" });
                    await new Promise(r => setTimeout(r, 300));
                    ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach(evType => {
                        firstOption.dispatchEvent(new MouseEvent(evType, { bubbles: true, cancelable: true, view: window }));
                    });
                    await new Promise(r => setTimeout(r, 1000));
                }
            } else {
                element.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", keyCode: 40, bubbles: true }));
                await new Promise(r => setTimeout(r, 500));
                element.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 13, bubbles: true }));
                await new Promise(r => setTimeout(r, 1000));
            }
        }
        element.blur();
    } catch (e) {
        element.value = value;
        element.dispatchEvent(new Event("input",  { bubbles: true }));
        element.dispatchEvent(new Event("change", { bubbles: true }));
    }
}
// ─────────────────────────────────────────────────────────────────
// AGGRESSIVE BUTTON CLICKERS
// ─────────────────────────────────────────────────────────────────
function _getFormActionBtn(modal) {
    return deepQuerySelectorAll("button", modal).find(btn => {
        const t = (btn.innerText || btn.textContent || "").toLowerCase().trim();
        const isAction = t === "next" || t === "review" || t.includes("submit") || t.includes("continue") || t === "agree";
        const isBack = t.includes("back") || t.includes("cancel");
        return isAction && !isBack && btn.getBoundingClientRect().width > 0;
    });
}

function _forceClickBtn(btn) {
    try {
        btn.scrollIntoView({ behavior: "smooth", block: "center" });
        // Strip the disabled attribute to force LinkedIn to show validation errors if stuck
        btn.removeAttribute("disabled"); 
        btn.classList.remove("disabled");
        btn.click();
        ["pointerdown", "mousedown", "pointerup", "mouseup"].forEach(evType => {
            btn.dispatchEvent(new MouseEvent(evType, { bubbles: true, cancelable: true, view: window }));
        });
    } catch(e) {}
}
// ─────────────────────────────────────────────────────────────────
// CORE LOGIC: SINGLE JOB APPLICATION
// ─────────────────────────────────────────────────────────────────
async function startSingleJobApply() {
    _jobStatus = "running";
    setAgentStatus("running");
    
    // 🌟 NEW: Scrape the HR Info from the job description page
    _foundHrName = null;
    _foundHrUrl = null;
    try {
        const hrNameEl = document.querySelector(".hirer-card__hirer-information .jobs-poster__name strong") || document.querySelector(".hirer-card__hirer-information .jobs-poster__name");
        const hrLinkEl = document.querySelector(".hirer-card__hirer-information a[href*='/in/']");
        
        if (hrNameEl && hrLinkEl) {
            _foundHrName = (hrNameEl.innerText || hrNameEl.textContent).trim();
            _foundHrUrl = hrLinkEl.href.split('?')[0]; // Clean the URL
            agentLog(`🎯 Found Job Poster: ${_foundHrName}`, "#8b5cf6");
        }
    } catch (e) {
        console.log("HR Scrape error:", e);
    }

    agentLog("👀 Hunting for Apply button in right pane...", "#38bdf8");
    
    try {
        await humanScroll();
        let easyApplyBtn = null;
        for (let i = 0; i < 15; i++) {
            const rightPane = document.querySelector("[data-sdui-screen*='SemanticJobDetails'], [role='main'], .jobs-search__job-details--container") || document.body;
            
            easyApplyBtn = deepQuerySelectorAll("button, a, [role='button']", rightPane).find(el => {
                const isLeftPane = el.closest('[componentkey="SearchResultsMainContent"]') || el.closest('.jobs-search-results-list');
                if (isLeftPane) return false;
                
                const t = (el.innerText || el.textContent || el.getAttribute("aria-label") || "").toLowerCase().trim();
                const isEasyApply = t === "easy apply" || t === "linkedin easy apply" || t.includes("easy apply");
                const isExternal = t.includes("company site") || t.includes("on site") || t.includes("external");
                return isEasyApply && !isExternal && !el.disabled && el.getBoundingClientRect().width > 0;
            });
            if (easyApplyBtn) break;
            await humanDelay(1000, 1500);
        }
        
        if (easyApplyBtn) {
            agentLog("🖱️ Easy Apply found! Clicking...", "#38bdf8");
            _forceClickBtn(easyApplyBtn); 
            agentLog("⏳ Waiting for modal to open...", "#cbd5e1");
            
            let modalOpened = false;
            for(let i=0; i<15; i++) {
                await humanDelay(500, 800);
                const m = deepQuerySelectorAll(".jobs-easy-apply-modal, .artdeco-modal").find(el => el.getBoundingClientRect().width > 100);
                if (m) { modalOpened = true; break; }
            }

            if (!modalOpened) {
                agentLog("❌ Modal failed to open. Skipping job.", "#fbbf24");
                _jobStatus = "skipped";
                setAgentStatus("idle");
                
                return;
            }
            await scanAndAnswerForm(1, 0);
        } else {
            agentLog("⏭️ Skipped: No internal Easy Apply button found.", "#fbbf24");
            _jobStatus = "skipped";
            setAgentStatus("idle");
            chrome.runtime.sendMessage({ action: "job_completed", status: "skipped" });
        }
    } catch (err) {
        agentLog(`❌ Fatal Error: ${err.message}`, "#ef4444");
        _jobStatus = "error";
        setAgentStatus("error");
        chrome.runtime.sendMessage({ action: "job_completed", status: "error" });
    }
}

async function scanAndAnswerForm(pageNum = 1, retryCount = 0) {
    const modal = getActiveModal();
    agentLog(`🔍 Scanning form fields (Page ${pageNum})...`, "#c084fc");

    // 🌟 THE FIX 1: Tick mandatory checkboxes (Privacy/Consent) BEFORE checking validation
    // 🌟 THE FIX: Aggressively tick ALL Terms & Conditions / Privacy / Consent checkboxes
    const allCheckboxes = deepQuerySelectorAll("input[type='checkbox']", modal);
    for (const cb of allCheckboxes) {
        if (!cb.checked && cb.getBoundingClientRect().width > 0) {
            // Extract the text next to the checkbox to see what it is asking
            const label = cb.closest('label') || document.querySelector(`label[for="${cb.id}"]`) || cb.parentElement;
            const text = (label ? (label.innerText || label.textContent) : "").toLowerCase();
            
            // If it's a loose checkbox OR it contains consent keywords, FORCE TICK IT!
            if (!cb.closest("fieldset") || text.includes("agree") || text.includes("terms") || text.includes("condition") || text.includes("privacy") || text.includes("acknowledge") || text.includes("consent")) {
                cb.click();
                cb.dispatchEvent(new Event("change", { bubbles: true }));
                await humanDelay(300, 500);
            }
        }
    }

    const errors = deepQuerySelectorAll(".artdeco-inline-feedback--error, [data-test-form-element-error-message]", modal).filter(e => e.getBoundingClientRect().width > 0);
    if (errors.length) {
        agentLog("❌ Hard Validation Error detected on page.", "#ef4444");
        await _abortCurrentApplication();
        _jobStatus = "error";
        // 🌟 THE FIX 2: Removed rogue sendMessage to prevent queue freezing
        return;
    }

    const actionBtn = _getFormActionBtn(modal);

    if (!actionBtn) {
        if (retryCount < 6) { 
            agentLog(`⚠️ Form buttons obscured or loading. Retrying (${retryCount+1}/6)...`, "#fbbf24");
            await _dismissBlockingModals();
            await humanDelay(1500, 2000); 
            return scanAndAnswerForm(pageNum, retryCount + 1); 
        }
        agentLog("❌ Lost the form modal or button. Aborting.", "#ef4444");
        await _abortCurrentApplication();
        _jobStatus = "error";
        return;
    }

    const questions = [], inputEls = [];
    const allInputs = deepQuerySelectorAll("input, select, textarea", modal);
    
    // 🌟 THE FIX 3: Cleaned up the question loop so it doesn't scan everything twice
    for (const label of deepQuerySelectorAll("label", modal)) {
        if (!label.getBoundingClientRect().width) continue;
        const inputId = label.getAttribute("for");
        if (!inputId) continue;
        const inp = allInputs.find(i => i.id === inputId);
        if (!inp || inp.disabled || inp.type === "hidden" || inp.type === "file") continue;
        if ((inp.type === "radio" || inp.type === "checkbox") && inp.closest("fieldset")) continue;

        let txt = (label.innerText || "").replace(/Required/ig, "").replace(/\*/g, "").trim();
        if (txt.length) { 
            let inputType = inp.type ? ` [Type: ${inp.type}]` : "";
            questions.push(txt + inputType); 
            inputEls.push(inp); 
        }
    }

    // Scan Fieldsets for Radio Button questions (Yes/No)
    for (const fs of deepQuerySelectorAll("fieldset", modal)) {
        if (!fs.getBoundingClientRect().width) continue;
        const legend = fs.querySelector("legend");
        if (!legend) continue;

        const radios = Array.from(fs.querySelectorAll("input[type='radio']"));
        if (radios.length === 0) continue;

        let txt = (legend.innerText || legend.textContent || "").replace(/Required/ig, "").replace(/\*/g, "").trim();
        if (txt.length) {
            questions.push(txt + " [Type: radio_yes_no]");
            inputEls.push(fs); 
        }
    }

    if (questions.length) {
        agentLog(`🧠 Found ${questions.length} questions. Asking Backend API...`, "#818cf8");
        
        let apiSuccess = false;
        let result = null;

        const store = await chrome.storage.local.get("saas_jwt_token");
        const headers = { "Content-Type": "application/json" };
        if (store.saas_jwt_token) headers["Authorization"] = "Bearer " + store.saas_jwt_token;

        // 🌟 THE FIX: Try up to 3 times with a 5-second cooldown if Groq rate-limits us!
        for (let attempt = 1; attempt <= 3; attempt++) {
            try {
                const resp = await fetch("https://ai-job-agent-backend-qmq1.onrender.com/api/answer-questions", {
                    method: "POST", headers: headers, body: JSON.stringify({ questions }),
                });
                result = await resp.json();
                
                if (result.status === "success") {
                    apiSuccess = true;
                    break; // Success! Exit the retry loop.
                } else {
                    agentLog(`⚠️ API Error (Attempt ${attempt}/3): ${result.message}`, "#fbbf24");
                    // If the user forgot to upload a resume, don't bother retrying
                    if (result.message && result.message.toLowerCase().includes("resume")) break; 
                    
                    agentLog("⏳ Cooling down for 5 seconds before retrying...", "#cbd5e1");
                    await humanDelay(4500, 5500); 
                }
            } catch (err) {
                agentLog(`⚠️ Network Error (Attempt ${attempt}/3): ${err.message}`, "#fbbf24");
                await humanDelay(4500, 5500);
            }
        }

        if (apiSuccess) {
            agentLog("✍️ Injecting answers into DOM...", "#818cf8");
                for (let i = 0; i < inputEls.length; i++) {
                    let ans = String(result.answers[i] || "Yes").trim();
                    const q = questions[i].toLowerCase();
                    
                     //1. Smart numerical defaults for missing AI answers
                    // 1. Smart numerical defaults for missing AI answers
                    if (ans === "Data Not Found" || ans === "0" || ans === "") {
                        if (q.includes("experience") || q.includes("years") || q.includes("how many")) ans = "2";
                        else if (q.includes("ctc") || q.includes("salary") || q.includes("pay")) ans = "300000";
                        else if (q.includes("gpa") || q.includes("cgpa") || q.includes("grade")) ans = "3.5";
                        
                        // 🌟 THE FIX: Added "how soon" and "days" to the notice period check
                        else if (q.includes("notice") || q.includes("availability") || q.includes("how soon") || q.includes("days")) ans = "30"; 
                        
                        else if (q.includes("year")) ans = new Date().getFullYear().toString();
                        else ans = "Yes";
                        
                        agentLog(`⚠️ Guessing missing answer for "${q.substring(0, 20)}..." -> ${ans}`, "#fbbf24");
                    }

                    // 2. Strict digit-only stripping for number fields
                    // 🌟 THE FIX: Added the new keywords here too so it strips out text!
                    if (q.includes("how many") || q.includes("experience") || q.includes("years") || q.includes("gpa") || q.includes("ctc") || q.includes("notice") || q.includes("how soon") || q.includes("days") || inputEls[i].type === "number") {
                        ans = ans.replace(/[^0-9.]/g, ""); 
                        if (ans === "") {
                            if (q.includes("notice") || q.includes("how soon") || q.includes("days")) ans = "30";
                            else if (q.includes("ctc")) ans = "300000";
                            else ans = "2"; 
                        }
                    }
                    
                    await setReactValue(inputEls[i], ans);
                    await humanDelay(600, 1000);
            }
        } else {
            agentLog(`❌ Backend API Failed after 3 attempts. Aborting job.`, "#ef4444");
            await _abortCurrentApplication();
            _jobStatus = "error";
            return; 
        }
    }

    const freshBtn = _getFormActionBtn(modal);
    if (!freshBtn) { await _abortCurrentApplication(); return; }

    const isSubmit = (freshBtn.innerText || "").toLowerCase().includes("submit");

    if (isSubmit) {
        agentLog("🚀 Form complete! Clicking Submit...", "#10b981");
        _forceClickBtn(freshBtn);
        await humanDelay(3500, 5000); 
        
        const postErrors = deepQuerySelectorAll(".artdeco-inline-feedback--error", modal).filter(e => e.getBoundingClientRect().width > 0);
        if (postErrors.length) {
            agentLog("❌ Validation Error occurred ON submit.", "#ef4444");
            await _abortCurrentApplication();
            _jobStatus = "error";
            return; 
        }
        
        agentLog("✅ DONE! Application successfully sent.", "#10b981");
        await humanDelay(1500, 2000);
        agentLog("🧹 Clearing success modal...", "#94a3b8");
        for (let k = 0; k < 3; k++) {
            await _dismissBlockingModals();
            const stillOpen = deepQuerySelectorAll(".jobs-easy-apply-modal, .artdeco-modal").find(m => m.getBoundingClientRect().width > 0 && window.getComputedStyle(m).display !== "none");
            if (!stillOpen) break;
            agentLog(`[Debug] Success modal still open, retrying kill... (${k+1})`, "#fbbf24");
        }
        _jobStatus = "success";
        
    } else {
        agentLog("➡️ Clicking Next...", "#cbd5e1");
        _forceClickBtn(freshBtn);
        await humanDelay(2500, 3500);
        await scanAndAnswerForm(pageNum + 1, 0);
    }
}
// ─────────────────────────────────────────────────────────────────
// 1. Get the new LazyColumn scroll container (ROBUST VERSION)
function _getJobListContainer() {
    // LinkedIn changes these classes constantly. We check all known variants!
    const selectors = [
        '.jobs-search-results-list',
        '.scaffold-layout__list',
        'div[data-testid="lazy-column"]',
        '.jobs-search__left-rail',
        '.jobs-search-results-list__wrapper'
    ];
    
    for (let sel of selectors) {
        const el = document.querySelector(sel);
        if (el) return el;
    }
    
    agentLog(`[Debug] Warning: Left-pane container not found. Fallback to Window.`, "#fbbf24");
    return window;
}

// 2. Find the new Job Cards (divs with role="button")
function _getEasyApplyCards() {
    const container = _getJobListContainer();
    const searchArea = container === window ? document : container;
    
    // New structure uses div[role="button"] with a specific componentkey
    let allCards = Array.from(searchArea.querySelectorAll('div[role="button"][componentkey^="job-card-component-ref-"]'));
    if (allCards.length === 0) {
        allCards = Array.from(searchArea.querySelectorAll(".job-card-container, div[data-job-id]"));
    }

    const finalCards = [];
    let appliedCount = 0;

    allCards.forEach(card => {
        if (card.dataset.agentProcessed) return;
        
        const text = (card.innerText || "").toLowerCase();
        // Catch jobs that are already applied so we don't waste time clicking them
        if (text.includes("applied ·") || text.match(/^applied$/m) || text.includes("application submitted")) {
            appliedCount++;
            return;
        }
        
        if (card.getBoundingClientRect().width > 0) {
            finalCards.push(card);
        }
    });

    agentLog(`[Debug] Scan: Found ${allCards.length} cards. Skipped ${appliedCount} applied. Valid: ${finalCards.length}`, "#d946ef");
    return finalCards;
}

// 3. Click the new card structure
function _clickCard(card) {
    const container = _getJobListContainer();
    if (container && container !== window) {
        const containerRect = container.getBoundingClientRect();
        const cardRect = card.getBoundingClientRect();
        if (cardRect.bottom > containerRect.bottom) {
            container.scrollBy({ top: cardRect.bottom - containerRect.bottom + 20, behavior: "smooth" });
        } else if (cardRect.top < containerRect.top) {
            container.scrollBy({ top: cardRect.top - containerRect.top - 20, behavior: "smooth" });
        }
    } else {
        card.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    
    setTimeout(() => {
        // LinkedIn removed the <a> tag; the whole card is now the button
        agentLog(`[Debug] Dispatching physical click to card...`, "#d946ef");
        ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach(evType => {
            card.dispatchEvent(new MouseEvent(evType, { bubbles: true, cancelable: true, view: window }));
        });
    }, 500);
}

// 4. Wait for the button, FORBIDDING the left pane
async function _waitForEasyApplyBtn(timeoutMs = 15000) {
    const end = Date.now() + timeoutMs;
    while (Date.now() < end) {
        await _dismissBlockingModals(); 
        // Added [role='main'] as a fallback for the new right pane structure
        const rightPane = document.querySelector("[data-sdui-screen*='SemanticJobDetails'], [role='main'], .jobs-search__job-details--container") || document.body;
        
        const btn = deepQuerySelectorAll("button, a, [role='button']", rightPane).find(el => {
            // 🛑 CRITICAL FIX: Only block the LEFT pane's lazy column, not the right pane's!
            const isLeftPane = el.closest('[componentkey="SearchResultsMainContent"]') || el.closest('.jobs-search-results-list');
            if (isLeftPane) return false;
            
            const t = (el.innerText || el.textContent || "").toLowerCase().trim();
            return (t === "easy apply" || t.includes("easy apply")) && !t.includes("company") && !el.disabled && el.getBoundingClientRect().width > 0;
        });
        if (btn) return btn;
        await humanDelay(500, 700);
    }
    return null;
}

async function _waitForApplyDone(timeoutMs = 120000) {
    const end = Date.now() + timeoutMs;
    while (Date.now() < end) {
        if (_jobStatus !== "running") return _jobStatus;
        await humanDelay(1000, 1500);
    }
    agentLog("⚠️ Process timed out.", "#ef4444");
    return "timeout";
}

// 🌟 NEW: One single function to handle all backend payloads!
function sendFinalPayload() {
    if (_jobStatus === "success") {
        agentLog("✅ Sending success signal & HR Data to Dashboard...", "#10b981");
        chrome.runtime.sendMessage({ 
            action: "job_completed", 
            status: "success",
            hr_name: _foundHrName,
            hr_url: _foundHrUrl
        });
    } else {
        agentLog(`⏭️ Job bypassed. Status: ${_jobStatus}`, "#fbbf24");
        chrome.runtime.sendMessage({ action: "job_completed", status: _jobStatus });
    }
}

// ─────────────────────────────────────────────────────────────────
// UNIFIED PIPELINE: HARVEST MANUALLY SEARCHED JOBS (BULLETPROOF)
// ─────────────────────────────────────────────────────────────────
function harvestAndQueueJobs() {
    agentLog("=======================================", "#64748b");
    agentLog("🚀 HARVESTING JOBS FROM SCREEN...", "#10b981");
    agentLog("=======================================", "#64748b");
    
    const jobIds = new Set();
    let rawSkippedLinks = 0;
    
    // 🌟 THE FIX: Ignore classes! Find ALL links on the page that point to a job.
    const jobLinks = document.querySelectorAll("a[href*='/jobs/view/'], a[href*='currentJobId=']");
    
    jobLinks.forEach(a => {
        // Find the container surrounding the link to check for "Applied" status
        const card = a.closest('li') || a.closest('.job-card-container') || a.closest('div[data-job-id]') || a.parentElement;
        
        if (card) {
            const text = (card.innerText || "").toLowerCase();
            if (text.includes("applied") || text.includes("application submitted")) {
                rawSkippedLinks++;
                return; // Skip this job!
            }
            // 🌟 THE FIX: Ignore external jobs completely!
            if (!text.includes("easy apply")) {
                return; // Skip if it doesn't say Easy Apply
            }
        }
        // Extract the Job ID securely from the link URL
        let jobId = null;
        const viewMatch = a.href.match(/\/jobs\/view\/(\d+)/);
        
        if (viewMatch) {
            jobId = viewMatch[1];
        } else {
            try {
                const urlObj = new URL(a.href, window.location.origin);
                jobId = urlObj.searchParams.get("currentJobId");
            } catch(e) {}
        }
        
        // Only add valid numerical Job IDs (LinkedIn IDs are usually 9-10 digits)
        if (jobId && /^\d+$/.test(jobId) && jobId.length >= 7) {
            jobIds.add(jobId);
        }
    });
    
    // LinkedIn has ~2-3 links per job card (Title, Logo, etc.), so we divide to get the real count
    const estimatedSkipped = Math.floor(rawSkippedLinks / 2);
    
    if (jobIds.size === 0) {
        agentLog(`⚠️ Skipped ~${estimatedSkipped} applied jobs. No new jobs found. Scroll down!`, "#fbbf24");
        return;
    }

    agentLog(`🎯 Skipped ~${estimatedSkipped} applied. Injecting ${jobIds.size} NEW jobs into Queue...`, "#8b5cf6");
    
    // Convert to the exact URL format the background script expects
    const urls = Array.from(jobIds).map(id => `https://www.linkedin.com/jobs/view/${id}/`);
    
    // Inject directly into the background.js Watchdog Queue!
    chrome.runtime.sendMessage({ action: "start_campaign", urls: urls }, (response) => {
        agentLog("✅ Jobs successfully added to the background queue!", "#10b981");
    });
}
// ─────────────────────────────────────────────────────────────────
// MESSAGE LISTENER
// ─────────────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    
    // 1. The Auto-SaaS Trigger (Handles BOTH Auto & Manual Jobs now!)
    if (request.action === "auto_start_apply") {
        agentLog("🚀 Agent Job Triggered...", "#3b82f6");
        
        startSingleJobApply().then(() => {
            if (_jobStatus === "success") {
                agentLog("✅ Sending success signal to Dashboard...", "#10b981");
                chrome.runtime.sendMessage({ 
                    action: "job_completed", 
                    status: "success",
                    hr_name: _foundHrName,
                    hr_url: _foundHrUrl
                });
            } else {
                agentLog(`⏭️ Job bypassed. Status: ${_jobStatus}`, "#fbbf24");
                chrome.runtime.sendMessage({ action: "job_completed", status: "skipped" });
            }
        }).catch((err) => {
            agentLog("❌ Fatal Error: " + err.message, "#ef4444");
            chrome.runtime.sendMessage({ action: "job_completed", status: "error" });
        });
        
        sendResponse({ status: "ok" });
        return true; 
    }

    // 2. The Manual Popup Trigger (Now Harvests instead of clicking!)
    if (request.action === "start_same_tab_campaign") {
        harvestAndQueueJobs();
        sendResponse({ status: "ok" });
        return false;
    }
});