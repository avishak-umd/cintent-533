"""Summarize a CIMonitor (setup-cintent) artifact per traced step:
process launches (execsnoop), file opens (opensnoop), and Python profile
self time grouped by origin (setprofile sandwich + graph CSVs)."""
import collections, csv, glob, os, re, sys

csv.field_size_limit(sys.maxsize)
D = sys.argv[1]
files = sorted(os.listdir(D))
steps = collections.defaultdict(lambda: collections.defaultdict(list))
for f in files:
    m = re.match(r"(\d+)\.(\d+)\.(.+)$", f)
    if m:
        steps[int(m.group(2))][m.group(3)].append(os.path.join(D, f))
print("files:", len(files))
for f in files:
    if not re.match(r"\d+\.\d+\.", f):
        print("  other:", f)

WS = "/home/runner/work/"
def origin(name, path):
    if path.startswith(WS):
        return "project:source"
    if "importlib" in path or path.startswith("<frozen"):
        return "stdlib:import-machinery"
    m = re.search(r"site-packages/([^/]+)", path) or re.search(r"dist-packages/([^/]+)", path)
    if m:
        return "pkg:" + re.sub(r"\.py$", "", m.group(1))
    m = re.search(r"/lib/python3\.\d+/([^/]+)", path)
    if m:
        mod = re.sub(r"\.py$", "", m.group(1))
        if mod == "subprocess" and name in ("wait", "_wait", "communicate", "_communicate", "_try_wait"):
            return "wait:subprocess"
        if mod in ("threading", "queue", "selectors", "multiprocessing", "concurrent") and name in (
                "wait", "join", "acquire", "get", "select", "_wait_for_tstate_lock", "result", "poll"):
            return "wait:thread/queue/process"
        return "stdlib:" + mod
    return "other:" + path[:40]

def profile(paths_sand, paths_graph):
    tot_self = collections.Counter(); proc_s = 0.0; nproc = 0; calls = collections.Counter()
    graphs = {}
    for g in paths_graph:
        key = os.path.basename(g).split(".")[0]
        out = collections.Counter(); seen = set()
        for r in csv.reader(open(g, errors="replace")):
            if not r or r[0] == "src_id" or tuple(r) in seen: continue
            seen.add(tuple(r)); out[r[0]] += int(float(r[3]))
        graphs[key] = out
    for s in paths_sand:
        key = os.path.basename(s).split(".")[0]
        out = graphs.get(key, collections.Counter())
        seen = set(); rows = []
        for r in csv.reader(open(s, errors="replace")):
            if not r or r[0] == "id" or len(r) < 7: continue
            k = tuple(r[:6])
            if k in seen: continue
            seen.add(k); rows.append(r)
        if not rows: continue
        nproc += 1
        proc_s += max(float(r[5]) for r in rows) / 1e9
        for r in rows:
            self_ns = max(0.0, float(r[5]) - out.get(r[0], 0))
            o = origin(r[1], r[2])
            tot_self[o] += self_ns / 1e9
            calls[(r[1], r[2].split("site-packages/")[-1][:70])] += int(r[4])
    return nproc, proc_s, tot_self, calls

for sid in sorted(steps):
    st = steps[sid]
    print("\n" + "=" * 70 + f"\nSTEP {sid}")
    for m in st.get("metadata.txt", []):
        print(open(m, errors="replace").read().strip()[:1500])
    # execsnoop
    execs = collections.Counter(); n_exec = 0
    for e in st.get("execsnoop.txt", []):
        for line in open(e, errors="replace"):
            p = line.split()
            if len(p) < 6 or p[0] == "TIME(s)": continue
            n_exec += 1; execs[p[1]] += 1
    print(f"execsnoop: {n_exec} process launches; top:", execs.most_common(12))
    # opensnoop
    n_open = 0; pk = collections.Counter(); ws = 0
    for o in st.get("opensnoop.txt", []):
        for line in open(o, errors="replace"):
            p = line.split(None, 6)
            if len(p) < 7 or p[0] == "TIME(s)": continue
            n_open += 1; path = p[6].strip()
            m = re.search(r"site-packages/([^/]+)", path)
            if m: pk[m.group(1).split("-")[0].replace(".py", "").lower()] += 1
            if path.startswith(WS): ws += 1
    print(f"opensnoop: {n_open} opens; {len(pk)} distinct site-packages entries; {ws} opens in workspace")
    print("  top site-packages:", pk.most_common(15))
    sand = st.get("setprofile.sandwich.csv", []); graph = st.get("setprofile.graph.csv", [])
    if sand:
        nproc, proc_s, self_t, calls = profile(sand, graph)
        wait = sum(v for k, v in self_t.items() if k.startswith("wait:"))
        total = sum(self_t.values())
        print(f"profile: {nproc} Python processes; root-frame seconds {proc_s:.1f}; self-time total {total:.1f}; wait {wait:.1f}; active {total - wait:.1f}")
        for k, v in self_t.most_common(10):
            print(f"  {k:35s} {v:9.1f} s  {100 * v / total:5.1f}%")
        print("  most-called:", [(f"{n}@{p}", c) for (n, p), c in calls.most_common(6)])
    else:
        print("profile: none (keys: %s)" % sorted(st))
