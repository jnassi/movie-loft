// Invariant test for the guide's scheduler (the JS inside guide.html).
//
//     node tests/guide_test.mjs                    # checks the built guide.html
//     node tests/guide_test.mjs some.html [label]  # or another build
//
// `make test` runs it twice: on a guide built from a made-up library
// (tests/guide_fixture.py — works in a fresh clone) and, if there is one, on
// the real guide.html.
//
// Runs the page's own buildDay() — lifted out of guide.html, so the test can't
// drift from what ships — over a run of days in America/Denver, including
// both daylight-saving changes, and checks the rules the guide promises:
//   - every broadcast day starts at 6 AM and ends at the next 6 AM (23/25 h on
//     DST days); nothing runs past it
//   - programs on a channel don't overlap and start on :00 or :30
//   - the same movie, or the same show, is never on two channels at once
//     (a loop channel excepted)
//   - only a test pattern can end a day early, and it runs to the end
//   - the lineup is deterministic: building a day twice gives the same thing
//   - Comfort channels only air tagged titles, and tagging leaves every other
//     channel untouched
process.env.TZ = 'America/Denver';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const file = process.argv[2] || fileURLToPath(new URL('../guide.html', import.meta.url));
const label = process.argv[3] || 'guide';
const html = readFileSync(file, 'utf8');
const a = html.indexOf('const MOVIES = '), b = html.indexOf('const cache = {};');
if (a < 0 || b < 0) { console.error(`can't find the scheduler in ${file}`); process.exit(2); }
const make = new Function(html.slice(a, b) +
  '\nreturn {MOVIES, SHOWS, CHANNELS, buildDay, dayStartFor, nextDayStart, setTags: t => { TAGS = t; }};');

const MIN = 60e3, SLOT = 30 * MIN;
const fails = [];
const fail = msg => { if (fails.length < 40) fails.push(msg); };

// A few ordinary days, plus the 2026 and 2027 DST changes on both sides.
const days = [];
for (const [y, m, d] of [[2026, 10, 17], [2026, 10, 18], [2026, 10, 31], [2026, 11, 1], [2026, 11, 2],
                         [2026, 12, 25], [2027, 3, 13], [2027, 3, 14], [2027, 3, 15], [2027, 7, 4]])
  days.push(new Date(y, m - 1, d, 6).getTime());

function check(g, start, label){
  const out = g.buildDay(start), end = g.nextDayStart(start);
  const hours = (end - start) / 3600e3;
  if (![23, 24, 25].includes(hours)) fail(`${label}: broadcast day is ${hours} h`);
  if (new Date(end).getHours() !== 6) fail(`${label}: day ends at ${new Date(end)}`);
  const airing = [];
  g.CHANNELS.forEach((ch, ci) => {
    const progs = out[ci], name = `${label} ${ch.name}`;
    if (!progs) return fail(`${name}: no schedule`);
    if (!progs.length) return;          // an empty channel (e.g. Comfort with nothing tagged)
    if (progs[0].start !== start) fail(`${name}: first program at ${new Date(progs[0].start)}`);
    progs.forEach((p, k) => {
      if (p.end > end) fail(`${name}: ${new Date(p.start)} runs past 6 AM`);
      if ((p.start - start) % SLOT) fail(`${name}: starts off the half hour at ${new Date(p.start)}`);
      if (k && p.start < progs[k - 1].end) fail(`${name}: overlaps the previous program at ${new Date(p.start)}`);
      if (p.pattern){
        if (k !== progs.length - 1 || p.end !== end) fail(`${name}: test pattern isn't the sign-off`);
        return;
      }
      if (!(p.end > p.start)) fail(`${name}: empty program at ${new Date(p.start)}`);
      if (!p.loop) airing.push([p.key, p.start, p.end, ch.name]);
    });
    const last = progs[progs.length - 1];
    if (!last.pattern && end - last.end >= SLOT) fail(`${name}: dead air after ${new Date(last.end)}`);
  });
  const byKey = {};
  for (const x of airing) (byKey[x[0]] = byKey[x[0]] || []).push(x);
  for (const list of Object.values(byKey)){
    list.sort((x, y) => x[1] - y[1]);
    for (let i = 1; i < list.length; i++){
      const [k, s, , c] = list[i], prev = list[i - 1];
      if (s < prev[2]){
        const what = k[0] === 'm' ? g.MOVIES[+k.slice(1)][1] : g.SHOWS[+k.slice(1)][0];
        fail(`${label}: ${what} on ${prev[3]} and ${c} at once (${new Date(s)})`);
      }
    }
  }
  return out;
}

const g = make();
for (const start of days){
  const label = new Date(start).toDateString();
  const first = check(g, start, label);
  if (JSON.stringify(make().buildDay(start)) !== JSON.stringify(first)) fail(`${label}: not deterministic`);
}

// Comfort: tag a few titles, then the Comfort channels air only those, and
// every other channel is exactly what it was untagged.
const comfort = g.CHANNELS.map((c, i) => c.kind.startsWith('comfort') ? i : -1).filter(i => i >= 0);
if (comfort.length){
  const start = days[0], before = make().buildDay(start);
  const tagged = make();
  const movies = new Set(tagged.MOVIES.slice(0, 40).map(m => m[0]));
  const shows = new Set(tagged.SHOWS.slice(0, 8).map(s => s[0]));
  tagged.setTags({movie: movies, show: shows});
  const after = check(tagged, start, 'tagged');
  after.forEach((progs, ci) => {
    const ch = tagged.CHANNELS[ci];
    if (comfort.includes(ci)){
      for (const p of progs) if (!p.pattern){
        const ok = p.kind === 'movie' ? movies.has(tagged.MOVIES[p.i][0]) : shows.has(tagged.SHOWS[p.s][0]);
        if (!ok) fail(`${ch.name} aired an untagged title`);
      }
      if (!progs.some(p => !p.pattern)) fail(`${ch.name} aired nothing with titles tagged`);
    } else if (JSON.stringify(progs) !== JSON.stringify(before[ci])){
      fail(`tagging changed ${ch.name}`);
    }
  });
}

const progs = days.length * g.CHANNELS.length;
if (fails.length){
  console.log(`${label}: ${fails.length}${fails.length >= 40 ? '+' : ''} problem(s)`);
  for (const f of fails) console.log('  - ' + f);
  process.exit(1);
}
console.log(`${label}: ok — ${days.length} days × ${g.CHANNELS.length} channels (${progs} channel-days), DST included`);
