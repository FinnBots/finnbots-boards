#!/usr/bin/env python3
"""boards_cloud.py — publish the FinnBots leaderboards from the cloud, Mac awake or not (2026-11-17).

Founder, 2026-11-17: "Lets just build A its only time and you can run this autonoumously for me".
Security review: factory/SECURITY-REVIEW-BOARDS.md (written before this file).

    python3 boards_cloud.py --scanner <scanner checkout>          one scan: state/ in, boards/ + state/ out
    python3 boards_cloud.py --scanner <dir> --state <dir> --out <dir> [--keep-log <file>]
    python3 boards_cloud.py --self-test --scanner <dir>             the rules below, on fixtures (no network)

WHAT IT RUNS: the UNCHANGED scanner's treasury scan, run_scan(), imported from the private scanner repo — the same code
the Mac runs, so a board cannot be ranked differently here. Nothing else: no earn scan, no rewards scan, no payout.
WHERE: a scratch HOME, so every ~/Desktop path the scanner uses lands in a throwaway folder seeded from state/.
WHAT IS KEPT: the treasury checkpoint + the leaderboards folder (boards, entry indexes, the names and fund ledgers) —
all public chain data. WHAT IS THROWN AWAY: every other file the scan writes (prize / spot / earn pending files and
their indexes): they are never committed, never published, never read by a payout. The Mac keeps the money.
WHAT IS PUBLISHED: boards/ = leaderboard_*.csv, cabinet_names.csv, build_funds.json.
WHAT IS PRINTED: counts only. The scan's own output (wallets, signatures, memos) goes to a file in the scratch folder
that is deleted, because this runs in a PUBLIC repo whose logs anyone can read.
A FAILED scan changes nothing: state/ and boards/ are only replaced after run_scan() returns cleanly.
Exit: 0 ok (changed or not) · 1 the scan failed (nothing written) · 2 usage.
"""
import contextlib, glob, io, json, os, re, shutil, sys, tempfile

PUBLISHED = re.compile(r"^(leaderboard_[a-z0-9]+\.csv|cabinet_names\.csv|build_funds\.json)$")
KEEP_DESKTOP = ("checkpoint_treasury_prod.txt",)          # treasury phase: the ONLY Desktop file it carries between runs
# THE FAUCET EARN BOARDS (2026-11-17; Founder: "fix the earn boards"): Flappy Bot + Pipeline rank faucet claims from
# earn_claims_index.csv, which the earn scan writes on the Desktop. Carried: the faucet checkpoints + that index (it IS the
# earn board, published since 10-16). Its pending_earn payout file dies with the scratch folder.
# NOT RUN HERE, deliberately: the E1 daily-challenge rewards phase. Its record (rewards_awards_index.csv) lists the wallets of
# PARENTS collecting a child's daily-challenge reward; this repo is PUBLIC, and a ready-made list of those wallets is not
# published even though each entry is on the chain. The earn caps share a daily limit with E1, so a wallet over its limit
# through E1 could read ACCEPTED here and OVER_CAP on the Mac — check-board-parity compares the earn list too, so such a
# difference is NAMED, never silent. The Mac (which pays) always judges with both.
PHASES = [  # (scanner function, the Desktop files that phase carries between runs, the ones it publishes)
    ("run_scan", ("checkpoint_treasury_prod.txt",), ()),
    ("run_earn_scan", ("checkpoint_faucet_prod.txt", "earn_scanner_checkpoint.txt", "earn_claims_index.csv"), ("earn_claims_index.csv",)),
]
ALL_KEEP = tuple(f for _, keep, _ in PHASES for f in keep)
LB_REL = os.path.join("Desktop", "FinnBots Games Factory", "leaderboards")


def _copy_tree(src, dst):
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(src) if os.path.isdir(src) else []:
        p = os.path.join(src, f)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(dst, f))


def seed(work, state):
    """Lay state/ out where the scanner expects it, under a scratch HOME."""
    desk, lb = os.path.join(work, "Desktop"), os.path.join(work, LB_REL)
    os.makedirs(lb, exist_ok=True)
    _copy_tree(os.path.join(state, "leaderboards"), lb)
    for f in ALL_KEEP:
        p = os.path.join(state, f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(desk, f))
    # public inputs the scan reads: the Bot mint list (holder check) and the Spot traits (its loader aborts without them)
    inputs = os.path.join(state, "inputs")
    if os.path.exists(os.path.join(inputs, "bots.json")):
        shutil.copy2(os.path.join(inputs, "bots.json"), os.path.join(desk, "bots.json"))
    if os.path.exists(os.path.join(inputs, "bot_traits.json")):
        shutil.copy2(os.path.join(inputs, "bot_traits.json"), os.path.join(desk, "bot_traits.json"))
    return desk, lb


def run_scan(scanner, work, log_path, phases=None):
    """Import the scanner with HOME = work and run its scan phases (the treasury first). Returns (ok, new_tx_count, out,
    phase_ok) — ok is the TREASURY phase (the boards); phase_ok names each phase that finished cleanly."""
    os.environ["HOME"] = work
    os.environ["FB_SCAN_PUBLIC_RPC"] = "1"                 # keyless: Solana's public RPC, the address fixed in the scanner
    os.environ.pop("HELIUS_API_KEY", None)
    sys.path.insert(0, scanner)
    buf = io.StringIO()
    phase_ok = {}
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        S = None
        try:
            for m in [m for m in list(sys.modules) if m in ("stage_prize_scanner", "factory_registry", "sinks", "rewards_claims")]:
                del sys.modules[m]
            import stage_prize_scanner as S              # noqa: E402 — must import AFTER HOME is set
        except BaseException as e:                        # noqa: BLE001
            buf.write("\nIMPORT FAILED " + type(e).__name__)
        for name, _, _ in (phases or PHASES):
            if S is None or not hasattr(S, name):
                phase_ok[name] = False
                continue
            mark = len(buf.getvalue())
            try:
                getattr(S, name)()
                phase_ok[name] = "ABORTING" not in buf.getvalue()[mark:]
            except SystemExit as e:
                phase_ok[name] = e.code in (None, 0)
            except Exception as e:                        # noqa: BLE001 — the TEXT is never printed (public logs)
                buf.write("\nEXCEPTION in " + name + " " + type(e).__name__ + ": " + str(e))
                phase_ok[name] = False
            if name == "run_scan" and not phase_ok[name]:
                break                                     # no boards without the treasury phase: stop, write nothing
    out = buf.getvalue()
    ok = phase_ok.get("run_scan", False)
    with open(log_path, "w") as f:
        f.write(out)
    m = re.search(r"Found (\d+) new transaction\(s\) to scan", out)
    return ok, (int(m.group(1)) if m else 0), out, phase_ok


def _funds(raw):
    try:
        return json.dumps(json.loads(raw).get("funds"), sort_keys=True)
    except Exception:  # noqa: BLE001 — unreadable = treat as changed
        return None


def harvest(desk, lb, state, out_dir, phase_ok=None):
    """Carry each CLEAN phase's state back to state/ and the public files to boards/. Returns the changed published files.
    A phase that failed carries nothing back: its old state stands, and the next run tries again."""
    os.makedirs(os.path.join(state, "leaderboards"), exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    phase_ok = phase_ok if phase_ok is not None else {"run_scan": True}
    changed = []
    for name, keep, publish in PHASES:
        if not phase_ok.get(name):
            continue
        for f in keep:
            p = os.path.join(desk, f)
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(state, f))
        for f in publish:
            p, dst = os.path.join(desk, f), os.path.join(out_dir, f)
            if os.path.exists(p) and (not os.path.exists(dst) or open(dst, "rb").read() != open(p, "rb").read()):
                shutil.copy2(p, dst); changed.append(f)
    _copy_tree(lb, os.path.join(state, "leaderboards"))
    for f in sorted(os.listdir(lb)):
        if not PUBLISHED.match(f):
            continue
        src, dst = os.path.join(lb, f), os.path.join(out_dir, f)
        new = open(src, "rb").read()
        if f == "build_funds.json" and os.path.exists(dst) and _funds(new) == _funds(open(dst, "rb").read()):
            continue                  # the scanner restamps "updated" every run: publish only when the TOTALS change
        if not os.path.exists(dst) or open(dst, "rb").read() != new:
            changed.append(f)
            with open(dst, "wb") as g:
                g.write(new)
    return changed


def one_run(scanner, state, out_dir, keep_log=None):
    work = tempfile.mkdtemp(prefix="fb-boards-")
    try:
        desk, lb = seed(work, state)
        ok, n, _, phase_ok = run_scan(scanner, work, os.path.join(work, "scan.log"))
        if keep_log:
            shutil.copy2(os.path.join(work, "scan.log"), keep_log)   # LOCAL debugging only — never in the workflow
        if not ok:
            print("scan FAILED — nothing written (state and boards unchanged)")
            return 1
        changed = harvest(desk, lb, state, out_dir, phase_ok)
        held = [name for name, _, _ in PHASES if not phase_ok.get(name)]
        print(f"scan ok · {n} new transaction(s) · {len(changed)} published file(s) changed"
              + (f" · phase(s) held at their last good state: {', '.join(held)}" if held else ""))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)               # every money-side file the scan wrote dies here


def self_test(scanner):
    """The rules, on fixtures, with a FAKE scanner module (no network)."""
    bad = 0
    def t(name, ok):
        nonlocal bad
        bad += 0 if ok else 1
        print(f"  {'✓' if ok else '✗'} {name}")
    root = tempfile.mkdtemp(prefix="fb-boards-test-")
    try:
        fake = os.path.join(root, "fake-scanner"); os.makedirs(fake)
        open(os.path.join(fake, "stage_prize_scanner.py"), "w").write(
            "import os, sys\n"
            "D = os.path.expanduser('~/Desktop'); L = os.path.join(D, 'FinnBots Games Factory', 'leaderboards')\n"
            "MODE = os.environ.get('FAKE_MODE', 'ok')\n"
            "def run_scan():\n"
            "    print('Found 3 new transaction(s) to scan.')\n"
            "    print('wallet 9xSECRETWALLETxx paid; memo BWRD|score|sig=abc')\n"
            "    if MODE == 'raise': raise RuntimeError('rpc said 9xSECRETWALLETxx')\n"
            "    if MODE == 'abort': print('ABORTING treasury scan: page bound'); return\n"
            "    open(os.path.join(D, 'checkpoint_treasury_prod.txt'), 'w').write('SIGNEW')\n"
            "    open(os.path.join(D, 'pending_prizes.csv'), 'w').write('wallet,prize\\n9xSECRETWALLETxx,300\\n')\n"
            "    open(os.path.join(D, 'pending_earn.csv'), 'w').write('x')\n"
            "    open(os.path.join(L, 'leaderboard_bwrd.csv'), 'w').write('rank,wallet\\n1,W\\n')\n"
            "    open(os.path.join(L, 'bwrd_entries_index.csv'), 'w').write('sig_prefix\\n')\n"
            "    open(os.path.join(L, 'cabinet_names.csv'), 'w').write('season,wallet,name\\n')\n"
            "    import time; open(os.path.join(L, 'build_funds.json'), 'w').write('{\"updated\": \"%s\", \"funds\": [1]}' % time.time())\n"
            "def run_earn_scan():\n"
            "    if os.environ.get('FAKE_EARN') == 'raise': raise RuntimeError('faucet rpc 9xSECRETWALLETxx')\n"
            "    open(os.path.join(D, 'checkpoint_faucet_prod.txt'), 'w').write('FNEW')\n"
            "    open(os.path.join(D, 'earn_claims_index.csv'), 'w').write('signature,wallet,claim_date,gates,status\\nS,W,2026-11-18,12,ACCEPTED\\n')\n"
            "    open(os.path.join(D, 'pending_earn.csv'), 'w').write('wallet,amount_oil\\nW,5\\n')\n"
            "def run_rewards_scan():\n"
            "    open(os.path.join(D, 'rewards_awards_index.csv'), 'w').write('wallet\\nPARENT\\n')\n")
        def fresh():
            st, ob = os.path.join(root, "state"), os.path.join(root, "boards")
            shutil.rmtree(st, ignore_errors=True); shutil.rmtree(ob, ignore_errors=True)
            os.makedirs(os.path.join(st, "leaderboards"))
            open(os.path.join(st, "checkpoint_treasury_prod.txt"), "w").write("SIGOLD")
            open(os.path.join(st, "leaderboards", "leaderboard_bwrd.csv"), "w").write("rank,wallet\n")
            return st, ob
        def go(mode, earn="ok"):
            os.environ["FAKE_MODE"] = mode; os.environ["FAKE_EARN"] = earn
            st, ob = fresh()
            home = os.environ.get("HOME")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = one_run(fake, st, ob)
            os.environ["HOME"] = home
            return rc, out.getvalue(), st, ob
        rc, out, st, ob = go("ok")
        t("the faucet EARN board is published and its checkpoint carried", "earn_claims_index.csv" in os.listdir(ob)
          and open(os.path.join(st, "checkpoint_faucet_prod.txt")).read() == "FNEW")
        everything = [os.path.basename(p) for p in glob.glob(os.path.join(root, "**", "*"), recursive=True)]
        t("the parents' daily-challenge rewards record is NEVER run, kept or published here", "rewards_awards_index.csv" not in everything)
        rc_e, out_e, st_e, ob_e = go("ok", earn="raise")
        t("a failed earn phase holds the earn board at its last good state, the paid boards still publish, nothing leaks",
          rc_e == 0 and "leaderboard_bwrd.csv" in os.listdir(ob_e) and "earn_claims_index.csv" not in os.listdir(ob_e)
          and not os.path.exists(os.path.join(st_e, "checkpoint_faucet_prod.txt")) and "SECRETWALLET" not in out_e and "held" in out_e)
        rc, out, st, ob = go("ok")
        t("a clean scan carries the checkpoint forward", open(os.path.join(st, "checkpoint_treasury_prod.txt")).read() == "SIGNEW")
        t("the boards, the cabinet names, the fund totals and the earn board are published", sorted(os.listdir(ob)) == ["build_funds.json", "cabinet_names.csv", "earn_claims_index.csv", "leaderboard_bwrd.csv"])
        t("the entry index is kept as STATE, never published", os.path.exists(os.path.join(st, "leaderboards", "bwrd_entries_index.csv")) and "bwrd_entries_index.csv" not in os.listdir(ob))
        allfiles = [os.path.basename(p) for p in glob.glob(os.path.join(root, "**", "*"), recursive=True)]
        t("prize / earn pending files are NEVER kept or published", "pending_prizes.csv" not in allfiles and "pending_earn.csv" not in allfiles)
        t("the log shows counts only — no wallet, no memo", "SECRETWALLET" not in out and "BWRD|" not in out and "3 new transaction" in out)
        for mode, label in (("raise", "a scan that throws"), ("abort", "a scan that aborts its page walk")):
            rc, out, st, ob = go(mode)
            t(f"{label} writes NOTHING and exits 1 — and its error text is not printed",
              rc == 1 and open(os.path.join(st, "checkpoint_treasury_prod.txt")).read() == "SIGOLD" and not os.path.exists(ob) and "SECRETWALLET" not in out)
        rc, out, st, ob = go("ok")
        before = {f: open(os.path.join(ob, f), "rb").read() for f in os.listdir(ob)}
        out2 = io.StringIO()
        with contextlib.redirect_stdout(out2):
            rc2 = one_run(fake, st, ob)
        after = {f: open(os.path.join(ob, f), "rb").read() for f in os.listdir(ob)}
        t("a second run with nothing new changes no published file — not even the fund totals' timestamp",
          rc2 == 0 and before == after and "0 published file(s) changed" in out2.getvalue())
    finally:
        os.environ.pop("FAKE_MODE", None); os.environ.pop("FAKE_EARN", None)
        shutil.rmtree(root, ignore_errors=True)
    print(f"  {'self-test clean' if not bad else 'SELF-TEST FAILED (' + str(bad) + ')'}")
    return 1 if bad else 0


def main(argv):
    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default
    here = os.path.dirname(os.path.abspath(__file__))
    scanner = opt("--scanner")
    if not scanner or not os.path.exists(os.path.join(scanner, "stage_prize_scanner.py")):
        print("usage: boards_cloud.py --scanner <scanner checkout> [--state state] [--out boards] | --self-test --scanner <dir>")
        return 2
    if "--self-test" in argv:
        return self_test(scanner)
    return one_run(os.path.abspath(scanner), os.path.abspath(opt("--state", os.path.join(here, "state"))),
                   os.path.abspath(opt("--out", os.path.join(here, "boards"))), opt("--keep-log"))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
