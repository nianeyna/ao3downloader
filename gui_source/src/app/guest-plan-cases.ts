// written by powershell_source/ao3_download_helper/dev/guest_plan_cases.py - do not edit.
// the helper's own checklist (server.step_plan) for each run and the choices that shape
// it: guest mode's pretend runs list the same (guest-runs.spec.ts, test_guest_steps.py)
export const GUEST_PLAN_CASES: { action: string; filetypes: string[]; options: Record<string, boolean | string>; plan: [string, string][] }[] = [
 {
  "action": "bookmarks",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index every bookmark"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "bookmarks",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "nonBookmarks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index every bookmark"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "bookmarks",
  "filetypes": [
   "JSON"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index every bookmark"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "bookmarks",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "nonBookmarks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index every bookmark"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "bookmarks",
  "filetypes": [
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Read the index already saved"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "quick",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "bookmarked",
    "Index bookmarks added since your last run"
   ],
   [
    "index",
    "Index works AO3 has updated since your last run"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "quick",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "nonBookmarks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "bookmarked",
    "Index bookmarks added since your last run"
   ],
   [
    "index",
    "Index works AO3 has updated since your last run"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "quick",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "dates": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "bookmarked",
    "Index bookmarks added in that date range"
   ],
   [
    "index",
    "Index works AO3 updated in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "quick",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "dates": true,
   "nonBookmarks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "bookmarked",
    "Index bookmarks added in that date range"
   ],
   [
    "index",
    "Index works AO3 updated in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "quick",
  "filetypes": [
   "JSON"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "bookmarked",
    "Index bookmarks added since your last run"
   ],
   [
    "index",
    "Index works AO3 has updated since your last run"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "quick",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "nonBookmarks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "bookmarked",
    "Index bookmarks added since your last run"
   ],
   [
    "index",
    "Index works AO3 has updated since your last run"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "quick",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "dates": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "bookmarked",
    "Index bookmarks added in that date range"
   ],
   [
    "index",
    "Index works AO3 updated in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "quick",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "dates": true,
   "nonBookmarks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "bookmarked",
    "Index bookmarks added in that date range"
   ],
   [
    "index",
    "Index works AO3 updated in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "quick",
  "filetypes": [
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "bookmarked",
    "Index bookmarks added since your last run"
   ],
   [
    "index",
    "Index works AO3 has updated since your last run"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "quick",
  "filetypes": [
   "HTML"
  ],
  "options": {
   "dates": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "bookmarked",
    "Index bookmarks added in that date range"
   ],
   [
    "index",
    "Index works AO3 updated in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index every bookmark"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "reindex": false
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Read the index already saved"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "recheck": true,
   "reindex": false
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index works AO3 has updated since that date"
   ],
   [
    "read",
    "Read every work in your index"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "nonBookmarks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index every bookmark"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "images": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index every bookmark"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "images",
    "Save embedded images separately"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "images": true,
   "reindex": false
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Read the index already saved"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "images",
    "Save embedded images separately"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "images": true,
   "nonBookmarks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index every bookmark"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "images",
    "Save embedded images separately"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "dates": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index works AO3 has updated since that date"
   ],
   [
    "read",
    "Find indexed works updated in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "dates": true,
   "order": "bookmarked"
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index bookmarks added in that date range"
   ],
   [
    "read",
    "Find indexed works bookmarked in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "dates": true,
   "nonBookmarks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index works AO3 has updated since that date"
   ],
   [
    "read",
    "Find indexed works updated in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "dates": true,
   "nonBookmarks": true,
   "order": "bookmarked"
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index bookmarks added in that date range"
   ],
   [
    "read",
    "Find indexed works bookmarked in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index every bookmark"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "reindex": false
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Read the index already saved"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "recheck": true,
   "reindex": false
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index works AO3 has updated since that date"
   ],
   [
    "read",
    "Read every work in your index"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "nonBookmarks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index every bookmark"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "images": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index every bookmark"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "images",
    "Save embedded images separately"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "images": true,
   "reindex": false
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Read the index already saved"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "images",
    "Save embedded images separately"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "images": true,
   "nonBookmarks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index every bookmark"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "images",
    "Save embedded images separately"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "dates": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index works AO3 has updated since that date"
   ],
   [
    "read",
    "Find indexed works updated in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "dates": true,
   "order": "bookmarked"
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index bookmarks added in that date range"
   ],
   [
    "read",
    "Find indexed works bookmarked in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "dates": true,
   "nonBookmarks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index works AO3 has updated since that date"
   ],
   [
    "read",
    "Find indexed works updated in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "dates": true,
   "nonBookmarks": true,
   "order": "bookmarked"
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index bookmarks added in that date range"
   ],
   [
    "read",
    "Find indexed works bookmarked in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "nonbookmarks",
    "Check remaining non-bookmarks for updates"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Read the index already saved"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "HTML"
  ],
  "options": {
   "recheck": true,
   "reindex": false
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "read",
    "Read every work in your index"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "HTML"
  ],
  "options": {
   "images": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Read the index already saved"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "images",
    "Save embedded images separately"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "HTML"
  ],
  "options": {
   "dates": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "read",
    "Find indexed works updated in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "custom",
  "filetypes": [
   "HTML"
  ],
  "options": {
   "dates": true,
   "order": "bookmarked"
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "read",
    "Find indexed works bookmarked in that date range"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Download or update each fic as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "new",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index bookmarks added since last time"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download newly added works"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "new",
  "filetypes": [
   "JSON"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index bookmarks added since last time"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "new",
  "filetypes": [
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index bookmarks added since last time"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download newly added works"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "sync",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index bookmarks added since last time"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download newly added works"
   ],
   [
    "update",
    "Re-index each fic, then download or update as necessary"
   ],
   [
    "gaps",
    "Fetch any format still missing"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "sync",
  "filetypes": [
   "JSON"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index bookmarks added since last time"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "update",
    "Re-index each fic, then download or update as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "sync",
  "filetypes": [
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index bookmarks added since last time"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download newly added works"
   ],
   [
    "update",
    "Re-index each fic, then download or update as necessary"
   ],
   [
    "gaps",
    "Fetch any format still missing"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "update",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "read",
    "Read existing index for unfinished fics"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Re-index each fic, then download or update as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "update",
  "filetypes": [
   "JSON"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "read",
    "Read existing index for unfinished fics"
   ],
   [
    "update",
    "Re-index each fic, then download or update as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "update",
  "filetypes": [
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "read",
    "Read existing index for unfinished fics"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "update",
    "Re-index each fic, then download or update as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "work",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index this fic"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download this fic"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "work",
  "filetypes": [
   "JSON"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index this fic"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "work",
  "filetypes": [
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index this fic"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download this fic"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "works",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index these fics"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download these fics"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "works",
  "filetypes": [
   "JSON"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index these fics"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "works",
  "filetypes": [
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index these fics"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download these fics"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "import",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index the works found in your library"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download the formats asked for"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "import",
  "filetypes": [
   "JSON"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index the works found in your library"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "import",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "replaceOutdated": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index the works found in your library"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download the formats asked for"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "import",
  "filetypes": [
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "index",
    "Index the works found in your library"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download the formats asked for"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collections",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collections",
    "Index your collections"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collections",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "collectionWorks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collections",
    "Index your collections and the works in them"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collections",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "collectionWorks": true,
   "series": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collections",
    "Index your collections and the works in them"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collections",
  "filetypes": [
   "JSON"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collections",
    "Index your collections"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collections",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "collectionWorks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collections",
    "Index your collections and the works in them"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collections",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "collectionWorks": true,
   "series": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collections",
    "Index your collections and the works in them"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collections",
  "filetypes": [
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collections",
    "Index your collections"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collections",
  "filetypes": [
   "HTML"
  ],
  "options": {
   "collectionWorks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collections",
    "Index your collections and the works in them"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collections",
  "filetypes": [
   "HTML"
  ],
  "options": {
   "collectionWorks": true,
   "series": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collections",
    "Index your collections and the works in them"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collection",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collection",
    "Index this collection"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collection",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "collectionWorks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collection",
    "Index this collection and the works in it"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collection",
  "filetypes": [
   "JSON",
   "HTML"
  ],
  "options": {
   "collectionWorks": true,
   "series": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collection",
    "Index this collection and the works in it"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collection",
  "filetypes": [
   "JSON"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collection",
    "Index this collection"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collection",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "collectionWorks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collection",
    "Index this collection and the works in it"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collection",
  "filetypes": [
   "JSON"
  ],
  "options": {
   "collectionWorks": true,
   "series": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collection",
    "Index this collection and the works in it"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collection",
  "filetypes": [
   "HTML"
  ],
  "options": {},
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collection",
    "Index this collection"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collection",
  "filetypes": [
   "HTML"
  ],
  "options": {
   "collectionWorks": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collection",
    "Index this collection and the works in it"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 },
 {
  "action": "collection",
  "filetypes": [
   "HTML"
  ],
  "options": {
   "collectionWorks": true,
   "series": true
  },
  "plan": [
   [
    "login",
    "Log in to AO3"
   ],
   [
    "collection",
    "Index this collection and the works in it"
   ],
   [
    "series",
    "Index works in series marked for walkthrough"
   ],
   [
    "check",
    "Read your existing downloaded files"
   ],
   [
    "download",
    "Download or update works as necessary"
   ],
   [
    "fichub",
    "Try FicHub for works AO3 would not give us"
   ],
   [
    "cleanup",
    "Cleanup"
   ],
   [
    "report",
    "Report any failures"
   ]
  ]
 }
];
