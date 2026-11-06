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
        AI Agent Telemetry
    </span>
    <button id="ai-copy-btn" style="background:#0a66c2;color:white;border:none;border-radius:4px;cursor:pointer;font-size:11px;padding:4px 8px;font-weight:bold;">Copy Logs</button>
`;

const logContainer = document.createElement("div");
logContainer.style.cssText = "flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 6px;";

panel.appendChild(header);
panel.appendChild(logContainer);

// Wait for body to be ready before appending
function _mountPanel() {
    if (document.body) {
        // Remove any stale panel from previous injection
        const old = document.getElementById("ai-agent-panel");
        if (old) old.remove();
        document.body.appendChild(panel);
        // getElementById works NOW because panel is in DOM
        const copyBtn = document.getElementById("ai-copy-btn");
        if (copyBtn) {
            copyBtn.addEventListener("click", () => {
                navigator.clipboard.writeText(logContainer.innerText);
                copyBtn.innerText = "Copied!";
                copyBtn.style.background = "#10b981";
                setTimeout(() => { copyBtn.innerText = "Copy Logs"; copyBtn.style.background = "#0a66c2"; }, 2000);
            });
        }
    } else {
        document.addEventListener("DOMContentLoaded", _mountPanel);
    }
}
_mountPanel();

// Re-mount if LinkedIn's SPA removes the panel during navigation
const _panelObserver = new MutationObserver(() => {
    if (!document.getElementById("ai-agent-panel")) {
        _mountPanel();
    }
});
_panelObserver.observe(document.documentElement, { childList: true, subtree: false });

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
// ─────────────────────────────────────────────────────────────────
// UTILITIES
// ─────────────────────────────────────────────────────────────────
let _jobStatus = "idle"; 
let _campaignRunning = false;
let _foundHrName = null;
let _foundHrUrl = null;
let _currentMatchScore = 0; // 🌟 NEW

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
// LINKEDIN NEW-UI HELPERS (hashed class names → use stable attributes only)
// Job cards  : div[role=button][componentkey^="job-card-component-ref-<ID>"]
// Apply btn  : button[aria-label="Easy Apply to this job"]
// Filter pill: label[aria-label="Filter by Easy Apply"]  (must NOT be clicked)
// ─────────────────────────────────────────────────────────────────
function _isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && window.getComputedStyle(el).visibility !== "hidden";
}

function _getCardId(el) {
    const ck = el.getAttribute && el.getAttribute("componentkey");
    const m = ck && ck.match(/^job-card-component-ref-(\d+)/);
    return m ? m[1] : null;
}

function _cardLooksApplied(text) {
    // Line-based so titles like "Applied AI Engineer" are NOT mistaken for "Applied · 2 days ago"
    return /^\s*applied\s*(·|$|\d|on\s|just now)/im.test(text) || /application submitted/i.test(text);
}

/** Collect unique, not-yet-applied job IDs from the left list (new + old LinkedIn layouts). */
function _collectJobIds() {
    const ids = new Set();
    let skipped = 0;
    const seen = new Set();

    // New layout: componentkey="job-card-component-ref-<id>" (outer + nested duplicates share the id)
    document.querySelectorAll('[componentkey^="job-card-component-ref-"]').forEach(el => {
        const id = _getCardId(el);
        if (!id || seen.has(id)) return;
        seen.add(id);
        const text = el.innerText || el.textContent || "";
        if (_cardLooksApplied(text)) { skipped++; return; }
        ids.add(id);
    });

    // Old layout fallbacks
    if (ids.size === 0 && seen.size === 0) {
        document.querySelectorAll("[data-job-id], [data-occludable-job-id], .job-card-container, li.scaffold-layout__list-item").forEach(card => {
            const text = card.innerText || "";
            const html = card.innerHTML || "";
            const m = (card.getAttribute("data-job-id") || card.getAttribute("data-occludable-job-id") || "").match(/^\d{7,}$/)
                   || html.match(/\/jobs\/view\/(\d{7,})/) || html.match(/currentJobId=(\d{7,})/i) || html.match(/jobposting:(\d{7,})/);
            const id = m && (m[1] || m[0]);
            if (!id || seen.has(id)) return;
            seen.add(id);
            if (_cardLooksApplied(text)) { skipped++; return; }
            ids.add(id);
        });
    }
    return { ids: Array.from(ids), skipped, total: seen.size };
}

/** The element that actually scrolls the left job list (found from the first card, no class names needed). */
function _findListScroller() {
    const first = document.querySelector('[componentkey^="job-card-component-ref-"]');
    let el = first ? first.parentElement : null;
    while (el && el !== document.body) {
        const cs = window.getComputedStyle(el);
        if (/(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 20) return el;
        el = el.parentElement;
    }
    return null;
}

/** Scroll the left list a few times so LinkedIn lazy-loads more cards (it only renders ~25 at first). */
async function _loadMoreCards(rounds = 4) {
    const scroller = _findListScroller();
    if (!scroller) return;
    for (let i = 0; i < rounds; i++) {
        const before = document.querySelectorAll('[componentkey^="job-card-component-ref-"]').length;
        scroller.scrollBy({ top: scroller.clientHeight * 0.9, behavior: "smooth" });
        await new Promise(r => setTimeout(r, 1200));
        const after = document.querySelectorAll('[componentkey^="job-card-component-ref-"]').length;
        if (after === before && i > 0) break;
    }
    scroller.scrollTo({ top: 0, behavior: "smooth" });
    await new Promise(r => setTimeout(r, 600));
}

/**
 * Find the REAL "Easy Apply" button of the job shown in the right pane.
 * Never matches: job cards (their text contains "Easy Apply"), the "Filter by Easy Apply" pill,
 * external "Apply" buttons, or anything inside the filter bar / left list.
 */
function _findEasyApplyButton() {
    const bad = el =>
        el.closest('[componentkey^="job-card-component-ref-"]') ||
        el.closest('[componentkey="JobsSearchFilters"], nav, [role="toolbar"]') ||
        /^filter by/i.test(el.getAttribute("aria-label") || "") ||
        el.disabled || !_isVisible(el);

    // 1) Exact: <button aria-label="Easy Apply to this job">
    let btn = Array.from(document.querySelectorAll('button[aria-label*="Easy Apply" i], a[aria-label*="Easy Apply" i]')).find(el => !bad(el));
    if (btn) return btn;

    // 2) Any real <button>/<a> whose own visible text is just "Easy Apply" / "LinkedIn Apply"
    btn = Array.from(document.querySelectorAll("button, a")).find(el => {
        if (bad(el)) return false;
        const t = (el.innerText || el.textContent || "").trim().toLowerCase();
        return t.length < 30 && (t === "easy apply" || t === "linkedin apply");
    });
    return btn || null;
}

/** Wait until the right pane shows the job we navigated to (soft: continues after timeout). */
async function _waitForRightPaneJob(jobId, timeoutMs = 12000) {
    if (!jobId) return;
    const end = Date.now() + timeoutMs;
    while (Date.now() < end) {
        if (document.querySelector(`[componentkey*="${jobId}"]:not([componentkey^="job-card-component-ref-"]), [id*="${jobId}"]`)) return;
        if (_findEasyApplyButton()) return;
        await new Promise(r => setTimeout(r, 500));
    }
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
            
            await new Promise(r => setTimeout(r, 2500)); 
            
            const container = element.closest('.jobs-easy-apply-form-section__grouping') || document.body;
            const dropdown = container.querySelector("[role='listbox'], .basic-typeahead__results");
            
            if (dropdown) {
                const options = dropdown.querySelectorAll("[role='option'], .basic-typeahead__result");
                if (options.length > 0) {
                    const firstOption = options[0];
                    firstOption.scrollIntoView({ behavior: "smooth", block: "nearest" });
                    await new Promise(r => setTimeout(r, 400));
                    ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach(evType => {
                        firstOption.dispatchEvent(new MouseEvent(evType, { bubbles: true, cancelable: true, view: window }));
                    });
                    await new Promise(r => setTimeout(r, 1000));
                }
            } else {
                element.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", keyCode: 40, bubbles: true }));
                await new Promise(r => setTimeout(r, 800));
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
        const isAction = t === "next" || t === "review" || t.includes("submit") || t.includes("continue") || t === "agree" || t.includes("review your");
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
        const _urlJobId = (window.location.href.match(/currentJobId=(\d+)/) || window.location.href.match(/\/jobs\/view\/(\d+)/) || [])[1];
        await _waitForRightPaneJob(_urlJobId);
        for (let i = 0; i < 15; i++) {
            easyApplyBtn = _findEasyApplyButton();
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
        }
    } catch (err) {
        if (err.message && (err.message.includes("Extension context") || err.message.includes("context invalidated") || err.message.includes("message channel"))) {
            console.log("[Agent] Page navigated mid-apply — extension context gone. Safe to ignore.");
            return;
        }
        agentLog(`❌ Fatal Error: ${err.message}`, "#ef4444");
        _jobStatus = "error";
        setAgentStatus("error");
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
    // 🌟 THE NEW RESUME FIX: Smart click logic
 const resumeLabel = document.querySelector('label[for*="urn:li:fsd_profileDocument"]');
 // 🌟 THE BULLETPROOF RESUME FIX
    const resumeInput = document.querySelector('input[type="radio"][value*="urn:li:fsd_profileDocument"]');

    if (resumeInput) {
        // Check the input itself AND its parent container for LinkedIn's "selected" visual state
        const container = resumeInput.closest('.ui-attachment, .artdeco-card') || resumeInput.parentElement;
        const isSelected = resumeInput.checked || 
                           resumeInput.getAttribute('aria-checked') === 'true' || 
                           (container && container.classList.contains('selected'));

        if (isSelected) {
            agentLog("⏭️ Resume is already selected. Skipping click.", "#cbd5e1");
        } else {
            agentLog("✅ Selecting the saved resume...", "#10b981");
            const preciseLabel = document.querySelector(`label[for="${resumeInput.id}"]`);
            if (preciseLabel) { preciseLabel.click(); } 
            else { resumeInput.click(); }
            await humanDelay(500, 800);
        }
    }


    // 🌟 THE BULLETPROOF RESUME FIX 🌟
    // Check if ANY resume is checked. If yes, leave it alone. If no, click the first one.
    const resumeInputs = deepQuerySelectorAll("input[type='radio'][value*='urn:li:fsd_profileDocument']", modal);
    if (resumeInputs.length > 0) {
        const anyChecked = resumeInputs.some(r => r.checked || r.getAttribute('aria-checked') === 'true' || (r.closest('.ui-attachment') && r.closest('.ui-attachment').classList.contains('selected')));
        
        if (anyChecked) {
            agentLog("⏭️ Resume is already ticked. Moving forward.", "#cbd5e1");
        } else {
            agentLog("✅ Resume not ticked. Ticking the default resume...", "#10b981");
            const firstResume = resumeInputs[0];
            const label = document.querySelector(`label[for="${firstResume.id}"]`);
            if (label) label.click();
            else firstResume.click();
            await humanDelay(500, 800);
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
        
        if (inp.value && (inp.value.includes("urn:li:fsd_profileDocument") || inp.value.includes("urn:li:fsd_coverLetterDocument"))) {
            continue;
        }
        if ((inp.type === "radio" || inp.type === "checkbox") && inp.closest("fieldset")) continue;
        
        const valStr = (inp.value || "").toLowerCase();
        const parentHtml = (inp.closest('.jobs-easy-apply-form-section__grouping') || inp.parentElement).innerHTML.toLowerCase();
        
        if (valStr.includes("urn:li:fsd_profiledocument") || 
            valStr.includes("coverletter") || 
            parentHtml.includes("resume") || 
            parentHtml.includes("cv") || 
            parentHtml.includes("cover letter")) {
            continue; 
        }

        let txt = (label.innerText || "").replace(/Required/ig, "").replace(/\*/g, "").trim();
        if (txt.length) { 
            let inputType = inp.type ? ` [Type: ${inp.type}]` : "";
            let optionsStr = "";
            
            if (inp.tagName.toLowerCase() === "select") {
                const opts = Array.from(inp.options).map(o => o.text.trim()).filter(t => t && !t.includes("Select"));
                if (opts.length > 0) optionsStr = ` [Options: ${opts.join(" | ")}]`;
            }
            
            questions.push(txt + inputType + optionsStr); 
            inputEls.push(inp); 
        }
    }

    for (const fs of deepQuerySelectorAll("fieldset", modal)) {
        if (!fs.getBoundingClientRect().width) continue;
        const legend = fs.querySelector("legend");
        if (!legend) continue;

        // 🌟 FIX: Include checkboxes so Lever ATS and custom forms are scanned
        const radios = Array.from(fs.querySelectorAll("input[type='radio'], input[type='checkbox']"));
        if (radios.length === 0) continue;

        let txt = (legend.innerText || legend.textContent || "").replace(/Required/ig, "").replace(/\*/g, "").trim();
        if (txt.length) {
            const labels = Array.from(fs.querySelectorAll("label")).map(l => l.innerText.trim()).filter(t => t);
            let optionsStr = labels.length > 0 ? ` [Options: ${labels.join(" | ")}]` : "";
            
            questions.push(txt + " [Type: radio]" + optionsStr);
            inputEls.push(fs); 
        }
    }

    if (questions.length) {
        agentLog(`🧠 Found ${questions.length} questions. Asking Backend API...`, "#818cf8");
        
        let apiSuccess = false;
        let result = null;

        // 🌟 NEW: Scrape Job Description for ATS Match
        const jdEl = document.querySelector("#job-details, .jobs-description-content__text");
        const jdText = jdEl ? jdEl.innerText.substring(0, 3000) : "";

        // ─────────────────────────────────────────────────────────────
        // ROOT-CAUSE FIX: All fetch() calls have been moved to background.js.
        // content.js runs inside LinkedIn's page and is subject to LinkedIn's
        // strict Content-Security-Policy, which blocks outbound requests to
        // our Cloud Run backend — especially on later form pages where the
        // CSP has fully propagated. background.js is a service worker and is
        // exempt from page-level CSP. Routing through sendMessage is the
        // correct, permanent fix for "Failed to fetch" network errors.
        // ─────────────────────────────────────────────────────────────

        // Step 1: Warm up Cloud Run via background.js (no CSP restrictions there)
        await new Promise((resolve) => {
            chrome.runtime.sendMessage({ action: "WARMUP_BACKEND" }, () => resolve());
        });

        // Step 2: Ask AI for answers — routed through background.js service worker
        for (let attempt = 1; attempt <= 3; attempt++) {
            try {
                result = await new Promise((resolve, reject) => {
                    // 50s total timeout covering Cloud Run cold start (30s+) + inference
                    const timeoutId = setTimeout(() => reject(new Error("Request timed out after 50s")), 50000);
                    chrome.runtime.sendMessage(
                        { action: "FETCH_AI_ANSWERS", questions: questions, job_description: jdText },
                        (response) => {
                            clearTimeout(timeoutId);
                            if (chrome.runtime.lastError) {
                                reject(new Error(chrome.runtime.lastError.message));
                            } else {
                                resolve(response);
                            }
                        }
                    );
                });

                if (result && result.status === "success") {
                    apiSuccess = true;
                    _currentMatchScore = result.match_score || 0;
                    agentLog(`🎯 AI ATS Match Score: ${_currentMatchScore}%`, "#10b981");
                    break;
                } else {
                    const msg = (result && result.message) || "Unknown error";
                    const isRateLimit = msg.includes("429") || msg.includes("rate") || msg.includes("quota");
                    agentLog(`⚠️ API Error (Attempt ${attempt}/3): ${msg}`, "#fbbf24");
                    if (msg.toLowerCase().includes("resume")) break;
                    const waitMs = isRateLimit ? (attempt * 15000) : 5000;
                    agentLog(`⏳ Cooling down for ${waitMs/1000}s before retrying...`, "#cbd5e1");
                    await humanDelay(waitMs, waitMs + 2000);
                }
            } catch (err) {
                agentLog(`⚠️ API Error (Attempt ${attempt}/3): ${err.message}`, "#fbbf24");
                const waitMs = attempt * 5000;
                await humanDelay(waitMs, waitMs + 2000);
            }
        }

        if (apiSuccess) {
            agentLog("✍️ Injecting answers into DOM...", "#818cf8");
                for (let i = 0; i < inputEls.length; i++) {
                    let ans = String(result.answers[i] || "Yes").trim();
                    const q = questions[i].toLowerCase();
                    const inp = inputEls[i];

                    // ── IDENTITY GUARD (client-side) ──────────────────────────────
                    // If the AI returned "Yes" / "No" / single digit for a phone / email / name field, it's wrong.
                    const isIdentityField = /phone|mobile|mobile phone|contact number|contact no|email address|full name|your name|location|city/.test(q);
                    if (isIdentityField && /^(yes|no|true|false|[0-9])$/i.test(ans.trim())) {
                        agentLog(`⚠️ Identity field "${q.substring(0,25)}..." got bad value "${ans}" — skipping injection.`, "#fbbf24");
                        continue; // Skip — don't overwrite LinkedIn's pre-filled value
                    }

                    //1. Smart numerical defaults for missing AI answers
                    // 1. Smart numerical defaults for missing AI answers
                    if (ans === "Data Not Found" || ans === "0" || ans === "") {
                        if (q.includes("experience") || q.includes("years") || q.includes("how many")) ans = "2";
                        else if (q.includes("ctc") || q.includes("salary") || q.includes("pay") || q.includes("ectc") || q.includes("compensation") || q.includes("lpa")) ans = "800000";
                        else if (q.includes("gpa") || q.includes("cgpa") || q.includes("grade")) ans = "3.5";
                        else if (q.includes("notice") || q.includes("availability") || q.includes("how soon") || q.includes("days")) ans = "30"; 
                        else if (q.includes("year")) ans = new Date().getFullYear().toString();
                        else ans = "Yes";
                        agentLog(`⚠️ Guessing missing answer for "${q.substring(0, 20)}..." -> ${ans}`, "#fbbf24");
                    }


                    // 2. Numeric field handling — salary/CTC checked FIRST to avoid YOE cap
                    const isSalaryField = /ctc|salary|pay|ectc|compensation|lpa|package|remuneration/.test(q);
                    const isYOEField = !isSalaryField && (
                        q.includes("how many") || q.includes("experience") ||
                        q.includes("years") || q.includes("notice") ||
                        q.includes("how soon") || q.includes("days") ||
                        q.includes("gpa") || q.includes("cgpa") ||
                        inp.type === "number"
                    );

                    if (isSalaryField) {
                        // Salary: strip non-digits, NEVER cap (800000 is correct, not hallucinated)
                        ans = ans.replace(/[^0-9]/g, "");
                        if (ans === "" || parseInt(ans) < 1000) {
                            ans = (q.includes("ectc") || q.includes("expected")) ? "1000000" : "800000";
                            agentLog(`⚠️ Salary fallback for: "${q.substring(0,30)}..."`, "#fbbf24");
                        }
                    } else if (isYOEField) {
                        ans = ans.replace(/[^0-9.]/g, "");
                        if (ans === "") {
                            if (q.includes("notice") || q.includes("how soon") || q.includes("days")) ans = "30";
                            else if (q.includes("gpa") || q.includes("cgpa")) ans = "3.5";
                            else ans = "2";
                        }
                        const numVal = parseFloat(ans);
                        // Round decimals for YOE fields
                        if (!isNaN(numVal) && (q.includes("experience") || q.includes("years") || q.includes("how many"))) {
                            ans = String(Math.round(numVal));
                        }
                        // Hard cap at 99 — LinkedIn max, and catches hallucinated years like 2024
                        if (!isNaN(parseFloat(ans)) && parseFloat(ans) > 99) {
                            agentLog(`⚠️ Capping "${ans}" → 2 for: "${q.substring(0,30)}..."`, "#fbbf24");
                            ans = "2";
                        }
                        // Secondary cap: no skill can have >40 years experience
                        if (!isNaN(parseFloat(ans)) && parseFloat(ans) > 40 && (q.includes("experience") || q.includes("years"))) {
                            ans = "2";
                        }
                    }
                    
                    await setReactValue(inp, ans);
                    await humanDelay(600, 1000);
            }
        } else {
            agentLog(`❌ Backend API Failed after 3 attempts. Trying to submit what's filled...`, "#fbbf24");
            const fallbackBtn = _getFormActionBtn(modal);
            if (fallbackBtn && (fallbackBtn.innerText || "").toLowerCase().includes("submit")) {
                agentLog("🚀 Attempting submit with pre-filled data...", "#10b981");
                _forceClickBtn(fallbackBtn);
                await humanDelay(3500, 5000);
                const postErrors = deepQuerySelectorAll(".artdeco-inline-feedback--error", modal)
                    .filter(e => e.getBoundingClientRect().width > 0);
                if (postErrors.length > 0) {
                    agentLog("❌ Validation errors — aborting.", "#ef4444");
                    await _abortCurrentApplication();
                    _jobStatus = "error";
                    return;
                }
                agentLog("✅ DONE! Application submitted (API fallback).", "#10b981");
                _jobStatus = "success";
                return;
            } else if (fallbackBtn) {
                agentLog("➡️ API failed — clicking Next to continue...", "#fbbf24");
                _forceClickBtn(fallbackBtn);
                await humanDelay(2000, 3000);
            } else {
                agentLog("❌ No button found — aborting.", "#ef4444");
                await _abortCurrentApplication();
                _jobStatus = "error";
                return;
            }
        }
    }

    const freshBtn = _getFormActionBtn(modal);
    if (!freshBtn) { await _abortCurrentApplication(); return; }

    const btnText = (freshBtn.innerText || freshBtn.textContent || "").toLowerCase().trim();
    const isSubmit = btnText.includes("submit");
    const isReview = btnText === "review" || btnText.includes("review your");

    if (isSubmit || isReview) {
        if (isReview) {
            // Click Review to get to the final Submit page
            agentLog("📋 Clicking Review to reach Submit page...", "#10b981");
            _forceClickBtn(freshBtn);
            await humanDelay(2500, 3500);
            // Now find and click the actual Submit button
            const submitBtn = deepQuerySelectorAll("button", modal).find(btn => {
                const t = (btn.innerText || btn.textContent || "").toLowerCase().trim();
                return t.includes("submit") && btn.getBoundingClientRect().width > 0;
            });
            if (submitBtn) {
                agentLog("🚀 Submit button found! Clicking...", "#10b981");
                _forceClickBtn(submitBtn);
                await humanDelay(3500, 5000);
            } else {
                agentLog("⚠️ No Submit button after Review — page may have changed", "#fbbf24");
                await scanAndAnswerForm(pageNum + 1, 0);
                return;
            }
        } else {
            agentLog("🚀 Form complete! Clicking Submit...", "#10b981");
            _forceClickBtn(freshBtn);
            await humanDelay(3500, 5000);
        } 
        
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
        // Keep Cloud Run warm during page transition — routed through background.js (no CSP)
        chrome.runtime.sendMessage({ action: "WARMUP_BACKEND" });
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
        const btn = _findEasyApplyButton();
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
async function harvestAndQueueJobs() {
    agentLog("=======================================", "#64748b");
    agentLog("🚀 HARVESTING JOBS FROM SCREEN...", "#10b981");
    agentLog("=======================================", "#64748b");

    await _loadMoreCards(4);
    const { ids, skipped, total } = _collectJobIds();
    agentLog(`[Debug] Cards on screen: ${total} | already applied: ${skipped} | new: ${ids.length}`, "#d946ef");

    if (ids.length === 0) {
        agentLog(`⚠️ Skipped ~${skipped} applied jobs. No new jobs found. Scroll down or change filters!`, "#fbbf24");
        return;
    }

    agentLog(`🎯 Skipped ~${skipped} applied. Injecting ${ids.length} NEW jobs into Queue...`, "#8b5cf6");
    const urls = ids.map(id => `https://www.linkedin.com/jobs/view/${id}/`);

    chrome.runtime.sendMessage({ action: "POLL_PENDING_JOBS" }, (data) => {
        void chrome.runtime.lastError;
        if (!data) return;
        if (data.target_roles && data.target_roles.length > 0) chrome.storage.local.set({ targetRoles: data.target_roles });
        if (data.target_locations && data.target_locations.length > 0) chrome.storage.local.set({ targetLocations: data.target_locations });
    });

    // Remember which Easy Apply search the user is on so every job is opened inside the same filters.
    try { await chrome.storage.local.set({ campaignSearchQuery: window.location.search }); } catch (e) {}

    chrome.runtime.sendMessage({ action: "start_campaign", urls }, () => {
        void chrome.runtime.lastError;
        agentLog("✅ Jobs successfully added to the background queue!", "#10b981");
    });
}
// ─────────────────────────────────────────────────────────────────
// MESSAGE LISTENER
// ─────────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────
// MESSAGE LISTENER
// ─────────────────────────────────────────────────────────────────
// 🌟 THIS LOCK PREVENTS MULTIPLE AGENTS FROM RUNNING AT ONCE
let isApplyingLock = false;

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    
    // 1. The Auto-SaaS Trigger
    if (request.action === "auto_start_apply") {
        if (isApplyingLock) {
            console.log("Agent already running. Ignoring duplicate trigger.");
            sendResponse({ status: "ignored_locked" });
            return true;
        }
        
        isApplyingLock = true; // 🔒 LOCK THE AGENT
        agentLog("🚀 Agent Job Triggered...", "#3b82f6");
        
        startSingleJobApply().then(() => {
            if (_jobStatus === "success") {
                agentLog("✅ Sending success signal to Dashboard...", "#10b981");
                chrome.runtime.sendMessage({ 
                    action: "job_completed", 
                    status: "success",
                    hr_name: _foundHrName,
                    hr_url: _foundHrUrl,
                    match_score: _currentMatchScore
                });
            } else {
                agentLog(`⏭️ Job bypassed. Status: ${_jobStatus}`, "#fbbf24");
                chrome.runtime.sendMessage({ action: "job_completed", status: "skipped" });
            }
            isApplyingLock = false; // 🔓 UNLOCK THE AGENT
        }).catch((err) => {
            agentLog("❌ Fatal Error: " + err.message, "#ef4444");
            chrome.runtime.sendMessage({ action: "job_completed", status: "error" });
            isApplyingLock = false; // 🔓 UNLOCK THE AGENT
        });
        
        sendResponse({ status: "ok" });
        return true; 
    }

    // 2. The Manual Popup Trigger
    if (request.action === "start_same_tab_campaign") {
        harvestAndQueueJobs();
        sendResponse({ status: "ok" });
        return false;
    }

    // 3. Auto Scan: Silent scrape — background.js opens this tab just to collect job IDs.
    if (request.action === "SCRAPE_JOBS_FOR_SCAN") {
        (async () => {
            await _loadMoreCards(2);
            const finalIds = _collectJobIds().ids;
            console.log(`[AutoScan] SCRAPE_JOBS_FOR_SCAN → extracted ${finalIds.length} Job IDs.`);
            sendResponse(finalIds);
        })();
        return true;
    }
});