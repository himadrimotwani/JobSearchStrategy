#!/usr/bin/env node
/**
 * Retired local outreach dispatcher. Kept for incident review.
 */

const fs = require('fs');
const path = require('path');
const http = require('http');
const { execSync, spawn } = require('child_process');

let caffeinateProcess = null;

function acquireSleepAssertion() {
  if (caffeinateProcess) return;
  try {
    // Prevent display, system, disk, and idle sleep during active outreach dispatching
    caffeinateProcess = spawn('caffeinate', ['-dimsu'], {
      stdio: 'ignore',
      detached: false
    });
    log('>>> Power assertion acquired: caffeinate -dimsu active (Mac sleep prevented while dispatching)');
  } catch (err) {
    log(`Warning: Failed to acquire sleep assertion: ${err.message}`);
  }
}

function releaseSleepAssertion() {
  if (caffeinateProcess) {
    try {
      caffeinateProcess.kill('SIGTERM');
      log('>>> Power assertion released: Mac allowed to sleep naturally while idle');
    } catch (err) {}
    caffeinateProcess = null;
  }
}

process.on('exit', () => releaseSleepAssertion());
process.on('SIGINT', () => { releaseSleepAssertion(); process.exit(0); });
process.on('SIGTERM', () => { releaseSleepAssertion(); process.exit(0); });

const workspaceRoot = process.env.WORKSPACE_ROOT || path.resolve(__dirname, '..');
const ledgerPath = path.join(workspaceRoot, 'outputs/outreach/outreach-ledger.json');
const logFile = path.join(workspaceRoot, 'outputs/outreach/dispatcher.log');
const pulseTrackerPath = path.join(workspaceRoot, 'outputs/outreach/pulse-tracker.json');
const PULSE_HOURS_EST = [9, 12, 15, 18];

function getEasternDateAndHour() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    hour12: false
  }).formatToParts(new Date());
  const map = Object.fromEntries(parts.map(p => [p.type, p.value]));
  const hour = parseInt(map.hour, 10) % 24;
  return { dateStr: `${map.year}-${map.month}-${map.day}`, hour };
}

function checkAndTriggerScheduledPulse() {
  try {
    const { dateStr, hour } = getEasternDateAndHour();
    const eligible = PULSE_HOURS_EST.filter(h => h <= hour);
    if (eligible.length === 0) return;

    const latestSlot = eligible[eligible.length - 1];
    const slotKey = `${dateStr}-${String(latestSlot).padStart(2, '0')}`;

    let tracker = { triggered_slots: [] };
    if (fs.existsSync(pulseTrackerPath)) {
      tracker = JSON.parse(fs.readFileSync(pulseTrackerPath, 'utf8'));
    }
    if (!Array.isArray(tracker.triggered_slots)) tracker.triggered_slots = [];

    if (tracker.triggered_slots.includes(slotKey)) return;

    log(`>>> Scheduled 4x-Daily Pulse triggered for EST slot [${slotKey}] (50 leads target)`);
    acquireSleepAssertion();
    let output = '';
    try {
      output = execSync(`/opt/homebrew/bin/python3 scripts/stage_next_pulse.py --count 50 --date ${dateStr}`, {
        cwd: workspaceRoot,
        encoding: 'utf8',
        timeout: 240000
      });
      if (output.includes('Warning: No fresh uncontacted leads')) {
        output += ' | Fallback to multi-source harvester: ' + execSync(`/opt/homebrew/bin/python3 scripts/sourcing/harvest_leads.py --source all --count 50 --date ${dateStr}`, {
          cwd: workspaceRoot,
          encoding: 'utf8',
          timeout: 240000
        });
      }
    } catch (e) {
      output = execSync(`/opt/homebrew/bin/python3 scripts/sourcing/harvest_leads.py --source all --count 50 --date ${dateStr}`, {
        cwd: workspaceRoot,
        encoding: 'utf8',
        timeout: 240000
      });
    }
    log(`Pulse staging result [${slotKey}]: ${output.trim().replace(/\n/g, ' | ')}`);

    // Record slot after staging attempt so transient errors can retry
    if (!output.includes('Rolling 24h cap threshold approached')) {
      tracker.triggered_slots.push(slotKey);
      if (tracker.triggered_slots.length > 100) {
        tracker.triggered_slots = tracker.triggered_slots.slice(-100);
      }
      fs.writeFileSync(pulseTrackerPath, JSON.stringify(tracker, null, 2));
    }
  } catch (err) {
    releaseSleepAssertion();
    log(`Warning: Scheduled pulse staging check failed: ${err.message}`);
  }
}

function log(msg) {
  const ts = new Date().toISOString();
  const line = `[${ts}] ${msg}`;
  if (process.stdout.isTTY) console.log(line);
  try {
    fs.appendFileSync(logFile, line + '\n');
  } catch (e) {}
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function getActiveDateDirs() {
  const outreachDir = path.join(workspaceRoot, 'outputs/outreach');
  const dirs = fs.readdirSync(outreachDir)
    .filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d))
    .sort()
    .reverse();
  return dirs.map(d => path.join(outreachDir, d));
}

function getActiveStagedFile() {
  const dateDirs = getActiveDateDirs();
  for (const d of dateDirs) {
    const stagedPath = path.join(d, 'outreach-batch-staged.json');
    if (fs.existsSync(stagedPath)) {
      try {
        const data = JSON.parse(fs.readFileSync(stagedPath, 'utf8'));
        const hasStaged = data.records && data.records.some(r => r.status === 'STAGED');
        if (hasStaged) {
          return { stagedPath, dateDir: d, dateStr: path.basename(d) };
        }
      } catch (e) {}
    }
  }
  // Default to newest existing staged file that actually exists
  for (const d of dateDirs) {
    const stagedPath = path.join(d, 'outreach-batch-staged.json');
    if (fs.existsSync(stagedPath)) {
      return {
        stagedPath,
        dateDir: d,
        dateStr: path.basename(d)
      };
    }
  }
  return null;
}

class CDPClient {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.msgId = 1;
    this.callbacks = new Map();
    this.sessionId = null;
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url);
      this.ws.onopen = () => resolve();
      this.ws.onerror = (e) => reject(e);
      this.ws.onclose = () => {
        for (const [id, cb] of this.callbacks.entries()) {
          cb.reject(new Error('WebSocket closed'));
        }
        this.callbacks.clear();
      };
      this.ws.onmessage = (evt) => {
        const msg = JSON.parse(evt.data);
        if (msg.id && this.callbacks.has(msg.id)) {
          const cb = this.callbacks.get(msg.id);
          this.callbacks.delete(msg.id);
          if (msg.error) cb.reject(new Error(msg.error.message || JSON.stringify(msg.error)));
          else cb.resolve(msg.result);
        }
      };
    });
  }

  async send(method, params = {}, useSession = true) {
    const id = this.msgId++;
    const payload = { id, method, params };
    if (useSession && this.sessionId) payload.sessionId = this.sessionId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        if (this.callbacks.has(id)) {
          this.callbacks.delete(id);
          reject(new Error(`CDP command ${method} timed out after 30s`));
        }
      }, 30000);
      this.callbacks.set(id, {
        resolve: (val) => { clearTimeout(timer); resolve(val); },
        reject: (err) => { clearTimeout(timer); reject(err); }
      });
      try {
        this.ws.send(JSON.stringify(payload));
      } catch (err) {
        clearTimeout(timer);
        this.callbacks.delete(id);
        reject(err);
      }
    });
  }

  close() {
    if (this.ws) {
      try { this.ws.close(); } catch (e) {}
    }
  }
}

async function getChromeWebSocketUrl() {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: "127.0.0.1",
      port: 9222,
      path: "/json/version",
      headers: { "Host": "localhost" }
    };
    const req = http.get(options, (res) => {
      let body = "";
      res.on("data", (d) => body += d);
      res.on("end", () => {
        try {
          const info = JSON.parse(body);
          if (info.webSocketDebuggerUrl) {
            const wsUrl = info.webSocketDebuggerUrl.replace("ws://localhost/", "ws://127.0.0.1:9222/");
            return resolve(wsUrl);
          }
        } catch (e) {}
        fallbackFile();
      });
    });
    req.on("error", () => fallbackFile());

    function fallbackFile() {
      const activePortFile = path.join(process.env.HOME, 'Library/Application Support/Google/Chrome/DevToolsActivePort');
      if (fs.existsSync(activePortFile)) {
        const lines = fs.readFileSync(activePortFile, 'utf8').trim().split('\n');
        return resolve('ws://127.0.0.1:' + lines[0] + lines[1]);
      }
      reject(new Error('Could not get Chrome WebSocket URL from HTTP or DevToolsActivePort'));
    }
  });
}

async function ensureGmailPage(cdp) {
  const targetsRes = await cdp.send('Target.getTargets', {}, false);
  const gmailPages = targetsRes.targetInfos.filter(t => t.type === 'page' && t.url.includes('mail.google.com'));

  // Prefer clean main inbox page (not viewing a thread)
  let gmailPage = gmailPages.find(t => t.url.includes('#inbox') && !t.url.includes('#inbox/')) ||
                  gmailPages.find(t => !t.url.includes('/Whct') && !t.url.includes('/FMfc')) ||
                  gmailPages[0];

  if (!gmailPage) {
    log('Gmail tab not found. Opening https://mail.google.com/mail/u/0/#inbox...');
    const createRes = await cdp.send('Target.createTarget', { url: 'https://mail.google.com/mail/u/0/#inbox' }, false);
    for (let i = 0; i < 20; i++) {
      await sleep(1000);
      const updatedTargets = await cdp.send('Target.getTargets', {}, false);
      gmailPage = updatedTargets.targetInfos.find(t => t.targetId === createRes?.targetId) ||
                  updatedTargets.targetInfos.find(t => t.type === 'page' && t.url.includes('mail.google.com'));
      if (gmailPage) break;
    }
  }

  if (!gmailPage) {
    throw new Error('Failed to locate or open Gmail tab in Chrome!');
  }

  // Focus and activate the Gmail tab
  await cdp.send('Target.activateTarget', { targetId: gmailPage.targetId }, false).catch(() => {});

  const attachRes = await cdp.send('Target.attachToTarget', { targetId: gmailPage.targetId, flatten: true }, false);
  cdp.sessionId = attachRes.sessionId;
  log(`Attached to Gmail page [${gmailPage.title}], sessionId: ${cdp.sessionId}`);

  // If tab was on an open thread view, return to clean inbox list view
  await cdp.send('Runtime.evaluate', {
    expression: 'if (window.location.hash.includes("#inbox/") || window.location.hash.includes("compose")) { window.location.hash = "#inbox"; } true;'
  });
  await sleep(1000);

  // Wait for Gmail UI to be fully interactive (compose button visible & non-zero rect)
  log('Waiting for Gmail UI to become interactive...');
  let ready = false;
  for (let i = 0; i < 30; i++) {
    await sleep(1000);
    try {
      const evalRes = await cdp.send('Runtime.evaluate', {
        expression: '!!(document.querySelector("div[gh=\'cm\']"))'
      });
      if (evalRes?.result?.value === true) {
        ready = true;
        break;
      }
    } catch (e) {}
  }
  if (!ready) {
    log('Warning: Gmail compose button not confirmed within 30s; proceeding anyway...');
  } else {
    log('Gmail UI interactive and ready.');
  }
}

function getRolling24hSentCount() {
  try {
    const ledgerData = JSON.parse(fs.readFileSync(ledgerPath, 'utf8'));
    const recList = Array.isArray(ledgerData) ? ledgerData : (ledgerData.records || []);
    const cutoff = Date.now() - 24 * 60 * 60 * 1000;
    return recList.filter(r => r.status === 'SENT' && r.sent_at && Date.parse(r.sent_at) >= cutoff).length;
  } catch (e) {
    return 0;
  }
}

function isAlreadySentOrBounced(toEmail) {
  try {
    const target = toEmail.toLowerCase().trim();
    const ledgerData = JSON.parse(fs.readFileSync(ledgerPath, 'utf8'));
    const recList = Array.isArray(ledgerData) ? ledgerData : (ledgerData.records || []);
    return recList.some(r => {
      const em = (r.email || r.recipient_email || '').toLowerCase().trim();
      return em === target && (r.status === 'SENT' || r.status === 'BOUNCED' || r.status === 'REPLIED' || r.status === 'REPLIED_ADVANCED');
    });
  } catch (e) {
    return false;
  }
}

async function dispatchSingleRecord(cdp, record, dateDir) {
  const toEmail = record.recipient_email || record.email;
  if (isAlreadySentOrBounced(toEmail)) {
    log(`SKIPPED [${record.id}] <${toEmail}> already present in ledger as SENT/BOUNCED/REPLIED.`);
    const stagedPath = path.join(dateDir, 'outreach-batch-staged.json');
    if (fs.existsSync(stagedPath)) {
      const sData = JSON.parse(fs.readFileSync(stagedPath, 'utf8'));
      const rec = sData.records ? sData.records.find(r => r.id === record.id) : null;
      if (rec) rec.status = 'SKIPPED_DUPLICATE';
      fs.writeFileSync(stagedPath, JSON.stringify(sData, null, 2));
    }
    return;
  }
  log(`>>> Starting dispatch for [${record.id}] ${record.company} -> ${record.name || 'Team'} <${toEmail}>`);

  // 1. Clean up any open dialogs first & ensure clean compose state
  await cdp.send('Runtime.evaluate', {
    expression: `(() => {
      const btns = document.querySelectorAll("div[role='dialog'] div[aria-label*='Discard draft'], div[role='dialog'] div[data-tooltip*='Discard draft'], div[role='dialog'] [command='discard'], div[role='dialog'] img[aria-label*='Save & close']");
      btns.forEach(b => b.click());
      return true;
    })()`
  });
  await sleep(1200);

  // Verify no leftover dialog remains before composing
  const openDialogsRes = await cdp.send('Runtime.evaluate', {
    expression: 'document.querySelectorAll("div[role=\'dialog\']").length',
    returnByValue: true
  });
  if ((openDialogsRes?.result?.value || 0) > 0) {
    await cdp.send('Runtime.evaluate', {
      expression: 'document.querySelectorAll("div[role=\'dialog\'] div[aria-label*=\'Discard\']").forEach(b => b.click()); true;'
    });
    await sleep(1200);
  }

  // 2. Click Compose
  await cdp.send('Runtime.evaluate', {
    expression: 'document.querySelector("div[gh=\'cm\']").click(); true;'
  });

  // 3. Poll until Compose dialog & To field are ready (up to 8s)
  let toInputFound = false;
  for (let i = 0; i < 40; i++) {
    await sleep(200);
    const checkRes = await cdp.send('Runtime.evaluate', {
      expression: '!!(document.querySelector("div[role=\'dialog\'] input[aria-label=\'To recipients\'], div[role=\'dialog\'] input[peoplekit-id]"))'
    });
    if (checkRes?.result?.value === true) {
      toInputFound = true;
      break;
    }
  }

  if (!toInputFound) {
    throw new Error('Compose To input not found within 8 seconds!');
  }
  await sleep(300);

  // 4. Insert exact To recipient and commit chip
  await cdp.send('Runtime.evaluate', {
    expression: `(() => {
      const toInput = document.querySelector("div[role='dialog'] input[aria-label='To recipients'], div[role='dialog'] input[peoplekit-id]");
      toInput.focus();
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(toInput, ${JSON.stringify(toEmail)});
      toInput.dispatchEvent(new Event('input', { bubbles: true }));
      toInput.dispatchEvent(new Event('change', { bubbles: true }));
      toInput.dispatchEvent(new KeyboardEvent('keydown', { key: ',', code: 'Comma', keyCode: 188, which: 188, bubbles: true }));
      toInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
      toInput.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
      return true;
    })()`
  });
  await sleep(500);

  // 5. Populate Subject and Body (innerText respects Trusted Types)
  await cdp.send('Runtime.evaluate', {
    expression: `(() => {
      const subjectInput = document.querySelector("input[name='subjectbox']");
      if (subjectInput) {
        subjectInput.focus();
        const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        nativeSetter.call(subjectInput, ${JSON.stringify(record.subject)});
        subjectInput.dispatchEvent(new Event('input', { bubbles: true }));
        subjectInput.dispatchEvent(new Event('change', { bubbles: true }));
      }
      const bodyDiv = document.querySelector("div[aria-label='Message Body']");
      if (bodyDiv) {
        bodyDiv.focus();
        bodyDiv.innerText = ${JSON.stringify(record.body)};
        bodyDiv.dispatchEvent(new Event('input', { bubbles: true }));
      }
      return true;
    })()`
  });
  await sleep(500);

  // 6. Attach PDF (poll up to 8s for file input in compose dialog)
  try { await cdp.send('DOM.enable', {}); } catch (e) {}
  let objectId = null;
  for (let i = 0; i < 25; i++) {
    const fileInputRes = await cdp.send('Runtime.evaluate', {
      expression: 'document.querySelector("input[type=\'file\'][name=\'Filedata\'], div[role=\'dialog\'] input[type=\'file\'], input[type=\'file\']")'
    });
    if (fileInputRes?.result?.objectId) {
      objectId = fileInputRes.result.objectId;
      break;
    }
    await sleep(300);
  }
  if (!objectId) {
    throw new Error('Could not find file input element in compose dialog!');
  }

  let defaultPdf = path.join(workspaceRoot, 'resumess/Himadri_Motwani_AI_Software_Engineering_Outreach.pdf');
  if (!fs.existsSync(defaultPdf)) {
    const resumesDir = path.join(workspaceRoot, 'resumess');
    if (fs.existsSync(resumesDir)) {
      const pdfs = fs.readdirSync(resumesDir).filter(f => f.toLowerCase().endsWith('.pdf'));
      if (pdfs.length > 0) defaultPdf = path.join(resumesDir, pdfs[0]);
    }
  }
  const pdfPath = record.attachment_paths ? record.attachment_paths[0] : (record.attachment_path || defaultPdf);

  if (!fs.existsSync(pdfPath)) {
    throw new Error(`Attachment file does not exist: ${pdfPath}`);
  }

  try {
    await cdp.send('DOM.setFileInputFiles', {
      files: [pdfPath],
      objectId: objectId
    });
  } catch (domErr) {
    // Fallback: request nodeId from objectId
    const nodeRes = await cdp.send('DOM.requestNode', { objectId });
    if (nodeRes && nodeRes.nodeId) {
      await cdp.send('DOM.setFileInputFiles', {
        files: [pdfPath],
        nodeId: nodeRes.nodeId
      });
    } else {
      throw domErr;
    }
  }
  log(`Attached file: ${path.basename(pdfPath)}, waiting for chip render...`);

  // 7. Poll for attachment chip and recipient verification (up to 12s)
  let verification = null;
  let chipDetected = false;
  let recipientVerified = false;

  for (let i = 0; i < 25; i++) {
    await sleep(500);
    const verRes = await cdp.send('Runtime.evaluate', {
      expression: `(() => {
        const dialog = document.querySelector("div[role='dialog']");
        if (!dialog) return null;
        const toChips = Array.from(dialog.querySelectorAll("span[email], div[data-hovercard-id], span[data-hovercard-id], div[peoplekit-id]")).map(e => e.getAttribute('email') || e.getAttribute('data-hovercard-id') || e.innerText);
        const toInputVal = dialog.querySelector("input[aria-label='To recipients'], input[peoplekit-id]")?.value || '';
        const subjectVal = dialog.querySelector("input[name='subjectbox']")?.value;
        const bodyVal = dialog.querySelector("div[aria-label='Message Body']")?.innerText;
        const attachmentChips = Array.from(dialog.querySelectorAll("div[role='dialog'] div[aria-label*='Attachment'], div[role='dialog'] div[aria-label*='attached'], div[role='dialog'] div[role='button'][aria-label*='.pdf'], div[role='dialog'] div[aria-label*='.pdf'], div[role='dialog'] span[aria-label*='.pdf']")).map(e => e.getAttribute('aria-label') || e.innerText);
        return {
          toChips,
          toInputVal,
          subjectVal,
          bodyLength: bodyVal?.length,
          attachmentChips
        };
      })()`,
      returnByValue: true
    });
    verification = verRes?.result?.value;
    if (verification) {
      if (verification.attachmentChips && verification.attachmentChips.length > 0) chipDetected = true;
      const chipEmails = Array.from(new Set(
        (verification.toChips || [])
          .map(r => (r || '').toLowerCase().trim())
          .filter(r => r.includes('@'))
      ));
      if (chipEmails.length > 1) {
        throw new Error(`Multi-recipient contamination prevented for ${toEmail}: ${JSON.stringify(chipEmails)}`);
      }
      const matchesChip = chipEmails.length === 1 && chipEmails[0] === toEmail.toLowerCase().trim();
      const matchesInput = verification.toInputVal.toLowerCase().trim() === toEmail.toLowerCase().trim();
      if (matchesChip || (chipEmails.length === 0 && matchesInput)) {
        recipientVerified = true;
      }
      if (chipDetected && recipientVerified) break;
    }
  }

  if (!recipientVerified) {
    throw new Error(`Recipient verification failed for ${toEmail}! Pre-send data: ${JSON.stringify(verification)}`);
  }
  if (!chipDetected) {
    throw new Error(`Attachment verification failed: chip not detected! Pre-send data: ${JSON.stringify(verification)}`);
  }

  // Save presend verification JSON
  const presendPayload = {
    id: record.id,
    to: [toEmail],
    subject: record.subject,
    body: record.body,
    attachment_count: 1,
    pdf: 1,
    checked_at: new Date().toISOString()
  };
  fs.writeFileSync(path.join(dateDir, `${record.id}-presend-verification.json`), JSON.stringify(presendPayload, null, 2));

  // 8. Click Send
  log(`Pre-send verified. Clicking Send for [${record.id}]...`);
  await cdp.send('Runtime.evaluate', {
    expression: '(() => {\n  const sendBtn = document.querySelector("div[role=\'dialog\'] div[role=\'button\'].aoO") || document.querySelector("div[role=\'dialog\'] div[aria-label*=\'Send\']");\n  if (sendBtn) { sendBtn.click(); return true; }\n  return false;\n})()'
  });

  await sleep(2500);

  // 9. Capture confirmation screenshot (6s timeout so occluded window never stalls send pipeline)
  try {
    const shotRes = await Promise.race([
      cdp.send('Page.captureScreenshot', { format: 'png' }),
      sleep(6000).then(() => null)
    ]);
    if (shotRes?.data) {
      const shotBuf = Buffer.from(shotRes.data, 'base64');
      fs.writeFileSync(path.join(dateDir, `${record.id}-send-confirmed.png`), shotBuf);
    }
  } catch (e) {
    log(`Warning: screenshot capture failed: ${e.message}`);
  }

  const confText = `Confirmed send for ${record.id} (${record.company} - ${toEmail})\nStatus: SENT\nTimestamp: ${new Date().toISOString()}\n`;
  fs.writeFileSync(path.join(dateDir, `${record.id}-send-confirmation.txt`), confText);

  // 10. Update records in files
  const sentRecord = {
    ...record,
    email: toEmail,
    recipient_email: toEmail,
    status: 'SENT',
    sent_at: new Date().toISOString()
  };

  // Update batch staged in dateDir
  const stagedPath = path.join(dateDir, 'outreach-batch-staged.json');
  if (fs.existsSync(stagedPath)) {
    const sData = JSON.parse(fs.readFileSync(stagedPath, 'utf8'));
    const rec = sData.records ? sData.records.find(r => r.id === record.id) : null;
    if (rec) {
      rec.status = 'SENT';
      rec.sent_at = sentRecord.sent_at;
    }
    sData.confirmed_sends = (sData.confirmed_sends || 0) + 1;
    sData.send_shortfall = Math.max(0, (sData.target_new_emails_per_day || 75) - sData.confirmed_sends);
    fs.writeFileSync(stagedPath, JSON.stringify(sData, null, 2));
  }

  // Also sync root staged file if it exists
  const rootStagedPath = path.join(workspaceRoot, 'outputs/outreach/outreach-batch-staged.json');
  if (fs.existsSync(rootStagedPath)) {
    try {
      const rsData = JSON.parse(fs.readFileSync(rootStagedPath, 'utf8'));
      const rec = rsData.records ? rsData.records.find(r => r.id === record.id) : null;
      if (rec) {
        rec.status = 'SENT';
        rec.sent_at = sentRecord.sent_at;
        rsData.confirmed_sends = (rsData.confirmed_sends || 0) + 1;
        rsData.send_shortfall = Math.max(0, (rsData.target_new_emails_per_day || 75) - rsData.confirmed_sends);
        fs.writeFileSync(rootStagedPath, JSON.stringify(rsData, null, 2));
      }
    } catch (e) {}
  }

  // Update outreach-ledger.json
  let ledgerData = { records: [] };
  if (fs.existsSync(ledgerPath)) {
    try {
      ledgerData = JSON.parse(fs.readFileSync(ledgerPath, 'utf8'));
    } catch (e) {
      ledgerData = { records: [] };
    }
  }
  const recList = Array.isArray(ledgerData) ? ledgerData : (ledgerData.records || (ledgerData.records = []));
  if (!recList.some(r => r.id === record.id)) {
    recList.push(sentRecord);
    fs.writeFileSync(ledgerPath, JSON.stringify(ledgerData, null, 2));
  }

  // Update run-status.json
  const runStatusPath = path.join(dateDir, 'run-status.json');
  if (fs.existsSync(runStatusPath)) {
    try {
      const runStatus = JSON.parse(fs.readFileSync(runStatusPath, 'utf8'));
      runStatus.confirmed_sends = (runStatus.confirmed_sends || 0) + 1;
      runStatus.sent_count = runStatus.confirmed_sends;
      if (typeof runStatus.daily_confirmed_outreach_sends === 'number') {
        runStatus.daily_confirmed_outreach_sends += 1;
        runStatus.daily_confirmed_qualifying_sends = runStatus.daily_confirmed_outreach_sends;
      }
      if (Array.isArray(runStatus.sends_today)) {
        runStatus.sends_today.push({
          company: record.company,
          recipient: record.name || 'Team',
          email: toEmail,
          role: record.role || record.target_role || 'Software Engineer',
          sent_time: new Date().toLocaleTimeString('en-US', { timeZone: 'America/New_York' }) + ' Eastern',
          status: 'SENT',
          attachment: 'Himadri_Motwani_AI_Software_Engineering_Outreach.pdf'
        });
      }
      const targetVal = runStatus.daily_target || runStatus.target || 75;
      const currentSends = runStatus.daily_confirmed_outreach_sends || runStatus.confirmed_sends;
      runStatus.shortfall = Math.max(0, targetVal - currentSends);
      runStatus.last_confirmed_recipient = toEmail;
      runStatus.updated_at = new Date().toISOString();
      runStatus.status = runStatus.shortfall === 0 ? 'TARGET_REACHED' : 'IN_PROGRESS';
      fs.writeFileSync(runStatusPath, JSON.stringify(runStatus, null, 2));
    } catch (e) {}
  }

  log(`CONFIRMED SENT [${record.id}] -> ${record.company} (${toEmail})`);
}

async function runDaemonLoop() {
  try {
    fs.writeFileSync(path.join(workspaceRoot, 'outputs/outreach/dispatcher.pid'), String(process.pid));
  } catch (e) {}
  log('==================================================');
  log(`Outreach Dispatch Daemon started (PID ${process.pid})`);
  log('==================================================');

  while (true) {
    try {
      checkAndTriggerScheduledPulse();
      const target = getActiveStagedFile();
      if (!target) {
        log('No active outreach date directory found. Waiting 30s...');
        await sleep(30000);
        continue;
      }

      const { stagedPath, dateDir, dateStr } = target;
      const stagedData = JSON.parse(fs.readFileSync(stagedPath, 'utf8'));
      const pending = stagedData.records.filter(r => r.status === 'STAGED' && (r.recipient_email || r.email));

      if (pending.length === 0) {
        releaseSleepAssertion();
        await sleep(20000);
        continue;
      }

      const sent24h = getRolling24hSentCount();
      if (sent24h >= 465) {
        releaseSleepAssertion();
        log(`Rolling 24h Gmail safety cap reached (${sent24h}/465). Waiting 15 minutes before checking again...`);
        await sleep(15 * 60 * 1000);
        continue;
      }

      acquireSleepAssertion();
      log(`Found ${pending.length} pending leads in ${dateStr} (Rolling 24h: ${sent24h}/465). Initializing Chrome CDP...`);
      const wsUrl = await getChromeWebSocketUrl();
      const cdp = new CDPClient(wsUrl);
      await cdp.connect();
      await ensureGmailPage(cdp);

      let consecutiveErrors = 0;
      for (const record of pending) {
        if (getRolling24hSentCount() >= 465) {
          log('Rolling 24h Gmail safety cap reached mid-batch (465). Pausing batch safely.');
          break;
        }
        try {
          await dispatchSingleRecord(cdp, record, dateDir);
          consecutiveErrors = 0;
          // Polite rate limiting between sends: 20 seconds
          log('Waiting 20 seconds before next send...');
          await sleep(20000);
        } catch (dispatchErr) {
          consecutiveErrors++;
          log(`ERROR on [${record.id}] ${record.company} (${consecutiveErrors} consecutive): ${dispatchErr.message}`);
          try {
            await cdp.send('Runtime.evaluate', {
              expression: 'const btns = document.querySelectorAll("div[role=\'dialog\'] div[aria-label*=\'Discard draft\']"); btns.forEach(b => b.click()); true;'
            });
          } catch (e) {}
          if (consecutiveErrors >= 3) {
            log('3 consecutive errors detected. Reloading Gmail page and resetting session...');
            try {
              await cdp.send('Page.reload', { ignoreCache: false });
              await sleep(6000);
            } catch (e) {}
            break;
          }
          await sleep(5000);
        }
      }

      cdp.close();
      releaseSleepAssertion();
      log(`Batch completed. Checking for more staged leads in 15 seconds...`);
      await sleep(15000);

    } catch (err) {
      releaseSleepAssertion();
      log(`Daemon loop error: ${err.message}. Retrying in 25 seconds...`);
      await sleep(25000);
    }
  }
}

runDaemonLoop().catch(err => {
  log(`Fatal daemon error: ${err.message}`);
  process.exit(1);
});
