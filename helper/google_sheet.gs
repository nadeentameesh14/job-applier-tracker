/**
 * Job Applier Tracker: keeps a Google Sheet in step with your bot's tracker.
 *
 * Setup (once): in your Google Sheet choose Extensions > Apps Script, paste this whole file over the
 * sample code, put any long random password in TOKEN below, then Deploy > New deployment > Web app,
 * "Execute as: Me", "Who has access: Anyone", and copy the web app URL. Add that URL and the same
 * password as the SHEET_WEBHOOK_URL and SHEET_TOKEN secrets in your private GitHub repo.
 *
 * Each run replaces the "Tracker" and "Scores" tabs with the bot's latest data, but it keeps:
 *  - anything you type in the "My notes" column, and
 *  - a status you set yourself to Interview, Offer or Rejected (or anything else you type in "My status").
 */
const TOKEN = 'change-me-to-a-long-random-password';
const KEEP_STATUSES = ['Interview', 'Offer', 'Rejected', 'Withdrawn'];

function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  if (body.token !== TOKEN) return out({ ok: false, error: 'wrong token' });
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  for (const name in body.tabs) {
    const tab = body.tabs[name];
    writeTab(ss, name, tab.header, tab.rows, tab.key || null);
  }
  // show the tracker first, and remove the blank starting tab
  const tr = ss.getSheetByName('Tracker');
  if (tr) { ss.setActiveSheet(tr); ss.moveActiveSheet(1); }
  const blank = ss.getSheetByName('Sheet1');
  if (blank && blank.getLastRow() === 0 && ss.getSheets().length > 1) ss.deleteSheet(blank);
  return out({ ok: true, url: ss.getUrl() });
}

function writeTab(ss, name, header, rows, key) {
  let sh = ss.getSheetByName(name) || ss.insertSheet(name);
  const old = sh.getDataRange().getValues();
  const oldHeader = old.length ? old[0].map(String) : [];
  const keep = {};
  if (key && old.length > 1) {
    const ki = oldHeader.indexOf(key), si = oldHeader.indexOf('status'), ni = oldHeader.indexOf('My notes'), mi = oldHeader.indexOf('My status');
    for (let r = 1; r < old.length; r++) {
      const id = String(old[r][ki]);
      keep[id] = { notes: ni >= 0 ? old[r][ni] : '', mine: mi >= 0 ? old[r][mi] : '', status: si >= 0 ? String(old[r][si]) : '' };
    }
  }
  let fullHeader = header.slice();
  if (key) fullHeader = ['My status'].concat(header, ['My notes']);
  const ki = header.indexOf(key), si = header.indexOf('status');
  const values = [fullHeader].concat(rows.map(function (row) {
    if (!key) return row;
    const k = keep[String(row[ki])] || {};
    if (si >= 0 && KEEP_STATUSES.indexOf(k.status) >= 0) row[si] = k.status;
    return [k.mine || ''].concat(row, [k.notes || '']);
  }));
  sh.clearContents();
  sh.getRange(1, 1, values.length, fullHeader.length).setValues(values);
  sh.setFrozenRows(1);
  sh.getRange(1, 1, 1, fullHeader.length).setFontWeight('bold');
}

function out(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
