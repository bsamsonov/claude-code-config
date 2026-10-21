// Collect all reel links of an Instagram profile from YOUR OWN logged-in browser.
// 1. Open https://www.instagram.com/<username>/reels/  (logged in, as usual).
// 2. F12 -> Console. Chrome may ask you to type: allow pasting
// 3. Paste this whole script, press Enter, do not touch the tab until it finishes.
// It scrolls like a human (random 1.5-3.5 s pauses), then saves <username>_reels.txt
// to Downloads (one URL per line, newest first). Re-run any time to get new reels.
(async () => {
  const user = location.pathname.split("/").filter(Boolean)[0] || "profile";
  const links = new Map();
  const grab = () => document.querySelectorAll('a[href*="/reel/"], a[href*="/p/"]').forEach(a => {
    const m = a.getAttribute("href").match(/\/(reel|p)\/([A-Za-z0-9_-]+)/);
    if (m && !links.has(m[2])) links.set(m[2], `https://www.instagram.com/reel/${m[2]}/`);
  });
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let idle = 0, last = 0;
  while (idle < 8) {
    grab();
    window.scrollBy(0, window.innerHeight * (0.8 + Math.random() * 0.6));
    await sleep(1500 + Math.random() * 2000);
    if (links.size === last) idle++; else { idle = 0; last = links.size; }
    console.log(`[collect] ${links.size} reels so far...`);
  }
  grab();
  const text = [...links.values()].join("\n") + "\n";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  a.download = `${user}_reels.txt`;
  document.body.appendChild(a); a.click(); a.remove();
  console.log(`[collect] done: ${links.size} reels saved to ${user}_reels.txt (Downloads)`);
})();
