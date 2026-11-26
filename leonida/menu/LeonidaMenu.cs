// C# 5 only (Script Hook V .NET's compiler): no exception filters, no $"", no "?.", no nameof, no auto-property
// initializers, no expression-bodied members, no out variables. tests/test_menu.py and build/check_menu.py compile
// it with csc -langversion:5 (against a stub and against the real ScriptHookVDotNet3.dll).
//
// LeonidaMenu: Leonida V's menu inside GTA V (Script Hook V .NET, API v3). Story mode only. Leonida installs it as
// scripts\LeonidaMenu.3.cs with scripts\LeonidaMenu.ini (a logged step, undone like any mod).
//
// What it does, and what it never does:
//   - It shows what Leonida knows (<State>\menu\menu-model.json, written by Leonida): the pack, its variant, the
//     game build, the mods and their locked settings, the keys and their clashes, help, the last play test.
//   - It never edits a mod's files or the game folder. Every change is a request in <State>\menu\menu-requests.json;
//     Leonida applies it through its installer (logged, undoable): at once when that's safe while playing (a
//     script's .ini, then a script reload), else after the game closes. Leonida's answers come back in the model.
//   - Open it with its key (scripts\LeonidaMenu.ini [Keys] Open, F5 by default) or, with iFruitAddon2, by calling
//     "Leonida" on the phone. Arrows / Enter / Backspace (or a controller's d-pad / A / B) move around.
//   - <State>\menu\selftest.flag (from `leonida playtest --deep`): it builds every page, draws each once, checks the
//     request queue both ways, checks the mods in game (the model's "checks": their `verify` entries), writes
//     <State>\menu\selftest-report.json and closes; no key presses needed.
//   - In-game setup (plan F8; data: leonida/zerotouch.py, model: leonida/ingame.py): per installed mod, its
//     `inGameSetup` actions instead of a hand step. "first-load": once per install stamp, 10 s after the player has
//     control. "verify-fails": every game start, check `verify` (a log: within its withinSeconds, default 15 s);
//     only if it fails do the action, once per game start, then check again after the reload and show `onFail`.
//     Actions: "reload-scripts" (Script Hook V .NET's own reload key) and "check" (`onFail` as a feed message).
//     What ran is kept in <State>\menu\menu-setup-done.json (saved before a reload, so a reload never repeats it)
//     and sent to Leonida as "setup" requests. Tools: "Run the in-game setup again". Checks only read the game
//     (IS_DLC_PRESENT, IS_IPL_ACTIVE, no-argument GET_/IS_/HAS_ natives, the mods' own files and logs).
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using GTA;
using GTA.Native;

public class LeonidaMenu : Script
{
    const string Version = "/*VERSION*/";
    const int VisibleRows = 14;
    const float PanelX = 0.025f, PanelW = 0.34f, TopY = 0.07f, RowH = 0.031f;
    const float Pad = 0.006f, Gap = 0.012f, LineH = 0.025f;        // text inset, gap between columns, box line step
    const float RowScale = 0.3f, FootScale = 0.27f, BoxScale = 0.26f;
    const int BoxLines = 4;                                        // the bottom box: a note or a row's full text
    readonly Dictionary<string, float> widths = new Dictionary<string, float>();
    const double ModelSeconds = 1.0;       // re-read the model this often while the menu is open
    const double ConnectedSeconds = 20;    // Leonida's heartbeat counts as "running" this long
    static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

    readonly string gameDir, scriptsDir, iniPath;
    string stateDir = "", bridgeDir = "", modelPath = "", requestsPath = "", flagPath = "", reportPath = "";
    Keys openKey = Keys.F5;
    Keys openModifier = Keys.None;
    bool open;
    Dictionary<string, object> model;
    DateTime modelReadAt = DateTime.MinValue, modelFileTime = DateTime.MinValue;
    readonly List<Dictionary<string, object>> requests = new List<Dictionary<string, object>>();
    int requestCounter;
    readonly List<Page> stack = new List<Page>();
    string note = "";
    DateTime noteUntil = DateTime.MinValue;
    // the phone entry (iFruitAddon2, through reflection: the menu also works without it)
    object phone;
    MethodInfo phoneUpdate;
    string phoneState = "not tried";
    // self-test
    bool selfTest;
    DateTime firstTick = DateTime.MinValue;
    int selfStage = -1, selfDrawn;
    string pingId;
    DateTime pingAt;
    readonly List<string> selfErrors = new List<string>();
    readonly Dictionary<string, int> selfPages = new Dictionary<string, int>();
    string selfAnswer;
    DateTime checksStart = DateTime.MinValue, checksAt = DateTime.MinValue, checksRun = DateTime.MinValue;
    bool checksAllOk;
    readonly Dictionary<string, List<object>> checkResults = new Dictionary<string, List<object>>();
    const double ChecksWaitSetup = 150;    // self-test: wait this long for the in-game setup to settle
    const double ChecksTimeout = 90;       // then retry the checks this long (an IPL can take a while)
    // in-game setup (plan F8)
    const double FirstLoadAfter = 10;      // seconds after the player has control
    const double DefaultWait = 15;         // verify-fails: how long the check may take to come true
    const double SetupGiveUp = 180;        // no model this long after the player has control: nothing to do
    string setupDonePath = "";
    readonly string processKey;
    readonly DateTime gameStartUtc;
    Dictionary<string, object> setupDone;
    List<SetupItem> setupQueue;
    readonly Dictionary<string, List<object>> setupResults = new Dictionary<string, List<object>>();
    readonly Dictionary<string, string> setupStamps = new Dictionary<string, string>();
    DateTime readySince = DateTime.MinValue;
    bool setupFinished, setupForce;
    string setupState = "waiting for story mode";

    class SetupItem
    {
        public string Mod = "", Stamp = "", Action = "", When = "", OnFail = "", DoneKey = "";
        public Dictionary<string, object> Verify;
        public bool Recheck, Due;
        public double Wait;
    }

    class Row
    {
        public string Text = "";
        public string Right = "";
        public bool Dim;
        public bool Warn;
        public Action Activate;
        public Action<int> Change;
    }

    class Page
    {
        public string Title = "";
        public Func<List<Row>> Build;
        public List<Row> Rows = new List<Row>();
        public int Sel, Top;
    }

    public LeonidaMenu()
    {
        gameDir = Directory.GetCurrentDirectory();
        scriptsDir = Path.Combine(gameDir, "scripts");
        iniPath = Path.Combine(scriptsDir, "LeonidaMenu.ini");
        processKey = ProcessKey(out gameStartUtc);
        ReadIni();
        LoadRequests();
        requestCounter = requests.Count;   // ids stay unique after a script reload
        selfTest = flagPath.Length > 0 && File.Exists(flagPath);
        Interval = 0;
        Tick += OnTick;
        KeyDown += OnKeyDown;
        Aborted += OnAborted;
    }

    // ------------------------------------------------------------------------------------------- settings
    void ReadIni()
    {
        try
        {
            if (!File.Exists(iniPath)) return;
            string section = "";
            foreach (string raw in File.ReadAllLines(iniPath))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith(";") || line.StartsWith("#")) continue;
                if (line.StartsWith("[") && line.EndsWith("]")) { section = line.Substring(1, line.Length - 2).Trim().ToLowerInvariant(); continue; }
                int eq = line.IndexOf('=');
                if (eq < 0) continue;
                string key = line.Substring(0, eq).Trim().ToLowerInvariant();
                string value = line.Substring(eq + 1).Trim();
                if (section == "leonida" && key == "statedir") SetState(value);
                if (section == "keys" && key == "open") ParseKey(value);
            }
        }
        catch (Exception ex) { Note("LeonidaMenu.ini: " + ex.Message); }
    }

    void SetState(string dir)
    {
        if (dir.Length == 0 || dir.StartsWith("{")) return;
        stateDir = dir;
        bridgeDir = Path.Combine(stateDir, "menu");
        modelPath = Path.Combine(bridgeDir, "menu-model.json");
        requestsPath = Path.Combine(bridgeDir, "menu-requests.json");
        flagPath = Path.Combine(bridgeDir, "selftest.flag");
        reportPath = Path.Combine(bridgeDir, "selftest-report.json");
        setupDonePath = Path.Combine(bridgeDir, "menu-setup-done.json");
    }

    void ParseKey(string text)
    {
        // "F5", or a chord like "Ctrl+F12" / "Shift+F5"
        string[] parts = text.Split('+');
        try
        {
            openKey = (Keys)Enum.Parse(typeof(Keys), parts[parts.Length - 1].Trim(), true);
            openModifier = Keys.None;
            for (int i = 0; i < parts.Length - 1; i++)
            {
                string m = parts[i].Trim().ToLowerInvariant();
                if (m == "ctrl" || m == "control") openModifier |= Keys.Control;
                else if (m == "shift") openModifier |= Keys.Shift;
                else if (m == "alt") openModifier |= Keys.Alt;
            }
        }
        catch (Exception) { Note("Unknown key in LeonidaMenu.ini: " + text + " (F5 is used)"); openKey = Keys.F5; }
    }

    // ------------------------------------------------------------------------------------------- the bridge
    void ReadModel(bool force)
    {
        if (modelPath.Length == 0) return;
        if (!force && (DateTime.UtcNow - modelReadAt).TotalSeconds < ModelSeconds) return;
        modelReadAt = DateTime.UtcNow;
        try
        {
            if (!File.Exists(modelPath)) return;
            DateTime t = File.GetLastWriteTimeUtc(modelPath);
            if (!force && t == modelFileTime && model != null) return;
            object parsed = LeonidaJson.Parse(File.ReadAllText(modelPath, Encoding.UTF8));
            Dictionary<string, object> d = parsed as Dictionary<string, object>;
            if (d == null) return;
            model = d;
            modelFileTime = t;
            PruneRequests();
            foreach (Page p in stack) p.Rows = p.Build();
        }
        catch (Exception) { /* a model being written right now: the next read gets it */ }
    }

    void LoadRequests()
    {
        try
        {
            if (requestsPath.Length == 0 || !File.Exists(requestsPath)) return;
            Dictionary<string, object> d = LeonidaJson.Parse(File.ReadAllText(requestsPath, Encoding.UTF8)) as Dictionary<string, object>;
            List<object> list = d == null ? null : Get(d, "requests") as List<object>;
            if (list == null) return;
            foreach (object o in list)
            {
                Dictionary<string, object> r = o as Dictionary<string, object>;
                if (r != null) requests.Add(r);
            }
        }
        catch (Exception) { }
    }

    string Request(string kind, Dictionary<string, object> fields)
    {
        Dictionary<string, object> r = new Dictionary<string, object>();
        string id = DateTime.UtcNow.ToString("yyyyMMddHHmmss", Inv) + "-" + (++requestCounter).ToString(Inv);
        r["id"] = id;
        r["kind"] = kind;
        r["at"] = DateTime.UtcNow.ToString("s", Inv) + "Z";
        if (fields != null) foreach (KeyValuePair<string, object> kv in fields) r[kv.Key] = kv.Value;
        requests.Add(r);
        WriteRequests();
        return id;
    }

    void WriteRequests()
    {
        if (requestsPath.Length == 0) { Note("Leonida's folder isn't set (scripts\\LeonidaMenu.ini): open Leonida once"); return; }
        try
        {
            Directory.CreateDirectory(bridgeDir);
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["schema"] = 1.0;
            d["menu"] = Version;
            d["requests"] = new List<object>(requests.ToArray());
            string tmp = requestsPath + ".tmp";
            File.WriteAllText(tmp, LeonidaJson.Write(d), new UTF8Encoding(false));
            if (File.Exists(requestsPath)) File.Delete(requestsPath);
            File.Move(tmp, requestsPath);
        }
        catch (Exception ex) { Note("Could not write the request for Leonida: " + ex.Message); }
    }

    void PruneRequests()
    {
        // requests Leonida has finished with (applied / refused / failed) leave the queue
        Dictionary<string, string> done = new Dictionary<string, string>();
        foreach (Dictionary<string, object> a in Applied())
        {
            string st = Str(a, "status");
            if (st != "pending") done[Str(a, "id")] = st;
        }
        int before = requests.Count;
        requests.RemoveAll(delegate(Dictionary<string, object> r) { return done.ContainsKey(Str(r, "id")); });
        if (requests.Count != before) WriteRequests();
    }

    List<Dictionary<string, object>> Applied()
    {
        List<Dictionary<string, object>> out1 = new List<Dictionary<string, object>>();
        List<object> list = model == null ? null : Get(model, "applied") as List<object>;
        if (list != null) foreach (object o in list) { Dictionary<string, object> d = o as Dictionary<string, object>; if (d != null) out1.Add(d); }
        return out1;
    }

    string AnswerFor(string id)
    {
        foreach (Dictionary<string, object> a in Applied()) if (Str(a, "id") == id) return Str(a, "status") + ": " + Str(a, "message");
        return null;
    }

    bool Connected()
    {
        if (model == null) return false;
        double beat = Num(model, "heartbeat");
        double now = (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        return now - beat < ConnectedSeconds;
    }

    // ------------------------------------------------------------------------------------------- the pages
    List<Row> StatusRows()
    {
        List<Row> rows = new List<Row>();
        if (model == null)
        {
            rows.Add(Info("Leonida hasn't written its menu data yet.", ""));
            rows.Add(Info("Start Leonida V: it fills this in.", ""));
            return rows;
        }
        Dictionary<string, object> st = Get(model, "status") as Dictionary<string, object>;
        if (st != null)
        {
            rows.Add(Info("Pack", Str(st, "pack")));
            rows.Add(Info("Variant", Str(st, "variant")));
            rows.Add(Info("Game build", Str(st, "build")));
            rows.Add(Info("Mods on", Str(st, "mods_on")));
            rows.Add(Info("Last play test", Str(st, "last_playtest")));
            string crash = Str(st, "crash");
            if (crash.Length > 0) { Row r = Info("Crash", crash); r.Warn = true; rows.Add(r); }
        }
        rows.Add(Info("Leonida", Connected() ? "running: changes apply" : "not running: open it to apply changes"));
        rows.Add(Info("Menu", Version + "  (" + KeyText() + ", phone: " + phoneState + ")"));
        rows.Add(Info("In-game setup", setupState));
        foreach (Dictionary<string, object> a in Applied())
        {
            Row r = Info(Str(a, "status"), Str(a, "message"));
            r.Dim = Str(a, "status") == "applied";
            r.Warn = Str(a, "status") == "refused" || Str(a, "status") == "failed";
            rows.Add(r);
        }
        return rows;
    }

    List<Row> ModsRows()
    {
        List<Row> rows = new List<Row>();
        foreach (Dictionary<string, object> m in Items(model, "mods"))
        {
            Dictionary<string, object> mod = m;
            Row r = new Row();
            r.Text = Str(mod, "name");
            r.Right = Bool(mod, "on") ? "on" : (Bool(mod, "disabled") ? "off (switched off)" : "off");
            r.Dim = !Bool(mod, "on");
            r.Activate = delegate { Push(Str(mod, "name"), delegate { return ModRows(Str(mod, "id")); }); };
            rows.Add(r);
        }
        if (rows.Count == 0) rows.Add(Info("No mods yet: Leonida lists them once it has written its data.", ""));
        return rows;
    }

    Dictionary<string, object> FindMod(string id)
    {
        foreach (Dictionary<string, object> m in Items(model, "mods")) if (Str(m, "id") == id) return m;
        return null;
    }

    List<Row> ModRows(string id)
    {
        List<Row> rows = new List<Row>();
        Dictionary<string, object> mod = FindMod(id);
        if (mod == null) { rows.Add(Info("This mod isn't in Leonida's data any more.", "")); return rows; }
        bool on = Bool(mod, "on") || (!Bool(mod, "disabled") && Bool(mod, "selected"));
        if (Bool(mod, "can_toggle"))
        {
            Row t = new Row();
            t.Text = "Switched on";
            t.Right = Bool(mod, "on") ? "yes" : "no";
            t.Activate = delegate
            {
                Dictionary<string, object> f = new Dictionary<string, object>();
                f["mod"] = id;
                f["on"] = !Bool(mod, "on");
                Request("mod", f);
                Note((Bool(mod, "on") ? "Switching off " : "Switching on ") + Str(mod, "name") + ": Leonida does it after you quit the game");
            };
            rows.Add(t);
        }
        foreach (Dictionary<string, object> s in Items(mod, "settings"))
        {
            Dictionary<string, object> setting = s;
            List<object> choices = Get(setting, "choices") as List<object>;
            int idx = -1;
            string current = Str(setting, "value");
            if (choices != null) for (int i = 0; i < choices.Count; i++) if (AsText(choices[i]) == current) idx = i;
            Row r = new Row();
            r.Text = Str(setting, "key");
            string shown = current;
            r.Right = shown + (Bool(setting, "unlocked") ? "  (yours)" : (choices == null ? "  (locked)" : "  <>"));
            r.Dim = choices == null && !Bool(setting, "unlocked");
            if (choices != null && choices.Count > 0)
            {
                int[] pick = { idx < 0 ? 0 : idx };
                r.Change = delegate(int step)
                {
                    pick[0] = (pick[0] + step + choices.Count) % choices.Count;
                    r.Right = AsText(choices[pick[0]]) + "  (Enter to use)";
                };
                r.Activate = delegate
                {
                    Dictionary<string, object> f = new Dictionary<string, object>();
                    f["mod"] = id;
                    f["file"] = Str(setting, "file");
                    f["key"] = Str(setting, "key");
                    f["value"] = AsText(choices[pick[0]]);
                    Request("setting", f);
                    Note(Str(setting, "key") + " = " + AsText(choices[pick[0]]) + (Bool(setting, "live") ? ": Leonida writes it now, then reload scripts" : ": Leonida writes it after you quit"));
                };
            }
            else
            {
                r.Activate = delegate { Note(Str(setting, "why").Length > 0 ? Str(setting, "why") : "Locked by Leonida; unlock it below to keep your own value"); };
            }
            rows.Add(r);
        }
        foreach (Dictionary<string, object> s in Items(mod, "settings"))
        {
            Dictionary<string, object> setting = s;
            bool unlocked = Bool(setting, "unlocked");
            Row u = new Row();
            u.Text = (unlocked ? "Lock again: " : "Unlock (advanced): ") + Str(setting, "key");
            u.Dim = true;
            u.Activate = delegate
            {
                Dictionary<string, object> f = new Dictionary<string, object>();
                f["mod"] = id;
                f["file"] = Str(setting, "file");
                f["key"] = Str(setting, "key");
                f["on"] = !unlocked;
                Request("unlock", f);
                Note(unlocked ? "Leonida locks it again" : "Unlocked: Leonida leaves your value in its file");
            };
            rows.Add(u);
        }
        foreach (string line in Wrap(Str(mod, "what"))) rows.Add(Info(line, ""));
        foreach (string line in Wrap(Str(mod, "help"))) { Row h = Info(line, ""); h.Dim = true; rows.Add(h); }
        if (!on && rows.Count == 0) rows.Add(Info("Not installed in this pack.", ""));
        return rows;
    }

    List<Row> PackRows()
    {
        List<Row> rows = new List<Row>();
        Dictionary<string, object> packs = model == null ? null : Get(model, "packs") as Dictionary<string, object>;
        if (packs == null) { rows.Add(Info("Leonida hasn't listed the packs yet.", "")); return rows; }
        List<Dictionary<string, object>> list = Items(packs, "list");
        string current = Str(packs, "current"), currentVariant = Str(packs, "variant");
        int pi = 0;
        for (int i = 0; i < list.Count; i++) if (Str(list[i], "id") == current) pi = i;
        if (list.Count > 0)
        {
            int[] pick = { pi };
            Row r = new Row();
            r.Text = "Pack";
            r.Right = Str(list[pi], "name") + "  <>";
            r.Change = delegate(int step) { pick[0] = (pick[0] + step + list.Count) % list.Count; r.Right = Str(list[pick[0]], "name") + "  (Enter to switch)"; };
            r.Activate = delegate
            {
                if (Str(list[pick[0]], "id") == current) { Note("That's your pack already"); return; }
                Dictionary<string, object> f = new Dictionary<string, object>();
                f["pack"] = Str(list[pick[0]], "id");
                Request("pack", f);
                Note("Switching to " + Str(list[pick[0]], "name") + ": Leonida does it after you quit");
            };
            rows.Add(r);
            List<Dictionary<string, object>> variants = Items(list[pi], "variants");
            if (variants.Count > 0)
            {
                int vi = 0;
                for (int i = 0; i < variants.Count; i++) if (Str(variants[i], "id") == currentVariant) vi = i;
                int[] vpick = { vi };
                Row v = new Row();
                v.Text = "Variant";
                v.Right = Str(variants[vi], "name") + "  <>";
                v.Change = delegate(int step) { vpick[0] = (vpick[0] + step + variants.Count) % variants.Count; v.Right = Str(variants[vpick[0]], "name") + "  (Enter to switch)"; };
                v.Activate = delegate
                {
                    if (Str(variants[vpick[0]], "id") == currentVariant) { Note("That's your variant already"); return; }
                    Dictionary<string, object> f = new Dictionary<string, object>();
                    f["variant"] = Str(variants[vpick[0]], "id");
                    Request("variant", f);
                    Note("Switching to " + Str(variants[vpick[0]], "name") + ": Leonida does it after you quit");
                };
                rows.Add(v);
            }
        }
        foreach (string line in Wrap(Str(packs, "note"))) { Row n = Info(line, ""); n.Dim = true; rows.Add(n); }
        return rows;
    }

    List<Row> GameRows()
    {
        List<Row> rows = new List<Row>();
        Dictionary<string, object> game = model == null ? null : Get(model, "game") as Dictionary<string, object>;
        if (game == null) { rows.Add(Info("Leonida hasn't read GTA's settings yet.", "")); return rows; }
        string preset = Str(game, "preset");
        if (preset.Length > 0) rows.Add(Info("Leonida's graphics preset", preset));
        foreach (Dictionary<string, object> v in Items(game, "values")) rows.Add(Info(Str(v, "name"), Str(v, "value")));
        foreach (string line in Wrap(Str(game, "note"))) { Row n = Info(line, ""); n.Dim = true; rows.Add(n); }
        return rows;
    }

    List<Row> KeysRows()
    {
        List<Row> rows = new List<Row>();
        foreach (Dictionary<string, object> k in Items(model, "keys"))
        {
            List<object> users = Get(k, "users") as List<object>;
            List<string> names = new List<string>();
            if (users != null) foreach (object u in users) names.Add(AsText(u));
            Row r = Info(Str(k, "label"), string.Join("; ", names.ToArray()));
            r.Warn = Bool(k, "clash");
            if (r.Warn) r.Text += "  (clash)";
            rows.Add(r);
        }
        if (rows.Count == 0) rows.Add(Info("Leonida hasn't listed the keys yet.", ""));
        return rows;
    }

    List<Row> HelpRows()
    {
        List<Row> rows = new List<Row>();
        foreach (Dictionary<string, object> m in Items(model, "mods"))
        {
            Dictionary<string, object> mod = m;
            if (!Bool(mod, "on")) continue;
            Row r = new Row();
            r.Text = Str(mod, "name");
            r.Right = ">";
            r.Activate = delegate
            {
                Push(Str(mod, "name"), delegate
                {
                    List<Row> lines = new List<Row>();
                    foreach (string line in Wrap(Str(mod, "what"))) lines.Add(Info(line, ""));
                    foreach (string line in Wrap(Str(mod, "help"))) lines.Add(Info(line, ""));
                    if (lines.Count == 0) lines.Add(Info("No notes for this mod.", ""));
                    return lines;
                });
            };
            rows.Add(r);
        }
        if (rows.Count == 0) rows.Add(Info("Help appears once Leonida has written its data.", ""));
        return rows;
    }

    List<Row> ToolsRows()
    {
        List<Row> rows = new List<Row>();
        string reload = model == null ? "" : Str(model, "reload_key");
        Row r = new Row();
        r.Text = "Reload scripts";
        r.Right = reload.Length == 0 || reload.ToLowerInvariant() == "none" ? "off in Script Hook V .NET" : reload;
        r.Activate = delegate { ReloadScripts(reload); };
        rows.Add(r);
        Row rep = new Row();
        rep.Text = "Make a debug report";
        rep.Right = "on your Desktop";
        rep.Activate = delegate { Request("report", null); Note("Leonida makes the report (logs and state, private details removed)"); };
        rows.Add(rep);
        Row after = new Row();
        after.Text = "Open Leonida after I quit";
        after.Activate = delegate { Request("open_leonida", null); Note("Leonida comes up when the game closes"); };
        rows.Add(after);
        int setupCount = model == null ? 0 : Items(model, "setup").Count;
        Row setup = new Row();
        setup.Text = "Run the in-game setup again";
        setup.Right = setupCount == 0 ? "no mod needs it" : setupCount.ToString(Inv) + (setupCount == 1 ? " mod" : " mods");
        setup.Dim = setupCount == 0;
        setup.Activate = delegate
        {
            if (setupCount == 0) { Note("No installed mod has in-game setup steps"); return; }
            RunSetupAgain();
        };
        rows.Add(setup);
        Row close = new Row();
        close.Text = "Close this menu";
        close.Activate = delegate { Close(); };
        rows.Add(close);
        return rows;
    }

    List<Row> RootRows()
    {
        List<Row> rows = new List<Row>();
        AddPage(rows, "Status", StatusRows);
        AddPage(rows, "Mods", ModsRows);
        AddPage(rows, "Pack & variant", PackRows);
        AddPage(rows, "Game settings", GameRows);
        AddPage(rows, "Keys", KeysRows);
        AddPage(rows, "Help", HelpRows);
        AddPage(rows, "Tools", ToolsRows);
        return rows;
    }

    void AddPage(List<Row> rows, string title, Func<List<Row>> build)
    {
        Row r = new Row();
        r.Text = title;
        r.Right = ">";
        r.Activate = delegate { Push(title, build); };
        rows.Add(r);
    }

    // ------------------------------------------------------------------------------------------- actions
    [DllImport("user32.dll")]
    static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);

    void ReloadScripts(string key)
    {
        if (key.Length == 0 || key.ToLowerInvariant() == "none") { Note("Script reloading is off in ScriptHookVDotNet.ini (ReloadKeyBinding)"); return; }
        try
        {
            Keys k = (Keys)Enum.Parse(typeof(Keys), key, true);
            Close();
            keybd_event((byte)k, 0, 0, UIntPtr.Zero);
            keybd_event((byte)k, 0, 2, UIntPtr.Zero);   // KEYEVENTF_KEYUP
        }
        catch (Exception) { Note("Press " + key + " to reload the scripts"); }
    }

    void Push(string title, Func<List<Row>> build)
    {
        Page p = new Page();
        p.Title = title;
        p.Build = build;
        try { p.Rows = build(); }
        catch (Exception ex) { p.Rows = new List<Row>(); p.Rows.Add(Info("This page failed: " + ex.Message, "")); selfErrors.Add(title + ": " + ex.Message); }
        stack.Add(p);
        Sound("SELECT");
    }

    void Open()
    {
        if (open) return;
        ReadModel(true);
        stack.Clear();
        Push("Leonida V", RootRows);
        open = true;
    }

    void Close()
    {
        open = false;
        stack.Clear();
        Sound("BACK");
    }

    void Note(string text)
    {
        note = text;
        noteUntil = DateTime.UtcNow.AddSeconds(6);
    }

    void Sound(string name)
    {
        try { Function.Call(Hash.PLAY_SOUND_FRONTEND, -1, name, "HUD_FRONTEND_DEFAULT_SOUNDSET", true); }
        catch (Exception) { }
    }

    // ------------------------------------------------------------------------------------------- in-game setup
    static string ProcessKey(out DateTime startUtc)
    {
        startUtc = DateTime.UtcNow;
        try
        {
            Process me = Process.GetCurrentProcess();
            startUtc = me.StartTime.ToUniversalTime();
            return me.Id.ToString(Inv) + "-" + startUtc.Ticks.ToString(Inv);
        }
        catch (Exception) { return "unknown"; }
    }

    bool PlayerReady()
    {
        int ped = Function.Call<int>(Hash.PLAYER_PED_ID);
        return ped != 0 && Function.Call<bool>(Hash.DOES_ENTITY_EXIST, ped)
            && Function.Call<bool>(Hash.IS_PLAYER_PLAYING, Function.Call<int>(Hash.PLAYER_ID))
            && !Function.Call<bool>(Hash.GET_IS_LOADING_SCREEN_ACTIVE)
            && Function.Call<bool>(Hash.IS_SCREEN_FADED_IN);
    }

    void SetupTick()
    {
        if (setupFinished || setupDonePath.Length == 0) return;
        if (Function.Call<bool>(Hash.NETWORK_IS_SESSION_STARTED)) return;   // story mode only
        if (!PlayerReady()) { if (!setupForce) readySince = DateTime.MinValue; return; }
        if (readySince == DateTime.MinValue) readySince = DateTime.UtcNow;
        double since = (DateTime.UtcNow - readySince).TotalSeconds;
        if (setupQueue == null)
        {
            ReadModel(false);
            if (model == null)
            {
                if (since > SetupGiveUp) { setupFinished = true; setupState = "no data from Leonida"; }
                return;
            }
            LoadSetupDone();
            setupQueue = PendingSetup();
            if (setupQueue.Count == 0) { setupFinished = true; setupState = "nothing to do"; return; }
            setupState = setupQueue.Count.ToString(Inv) + " step(s) to do";
        }
        bool waiting = false;
        for (int i = 0; i < setupQueue.Count; i++)
        {
            SetupItem it = setupQueue[i];
            if (it.Due) continue;
            if (!StepSetup(it, since)) { waiting = true; continue; }
            if (!it.Due) { setupQueue.RemoveAt(i); i--; }
        }
        if (waiting) return;
        // only reloads are left (they restart this script too, so they go last, after everything is saved)
        string key = model == null ? "" : Str(model, "reload_key");
        List<Keys> keys = key.Length > 0 && key.ToLowerInvariant() != "none" ? ParseKeys(key) : null;
        foreach (SetupItem it in setupQueue)
            Record(it, keys != null, it.When == "verify-fails" ? "acted" : "done",
                   keys != null ? "pressed " + key + " (Script Hook V .NET reloads the scripts)"
                                : "Script Hook V .NET has no reload key (ReloadKeyBinding), so it couldn't reload");
        bool reload = setupQueue.Count > 0 && keys != null;
        setupQueue.Clear();
        SaveSetupDone();
        ReportSetup();
        setupFinished = true;
        setupForce = false;
        setupState = reload ? "reloading the scripts" : "done";
        if (reload) PressKeys(keys);
    }

    // One step of an action. False = not yet (keep waiting); true = handled (recorded, or marked Due for a reload).
    bool StepSetup(SetupItem it, double since)
    {
        if (it.Action != "reload-scripts" && it.Action != "check")
        {
            Record(it, false, "done", "this menu doesn't know the action " + it.Action + " (update Leonida)");
            return true;
        }
        if (it.When == "first-load" && !it.Recheck)
        {
            if (since < FirstLoadAfter) return false;
            if (it.Action == "reload-scripts") { it.Due = true; return true; }
            string d;
            int r = Check(it.Verify, out d);
            if (r < 0 && since < FirstLoadAfter + it.Wait) return false;
            if (r == 0 && it.OnFail.Length > 0) Feed(it.OnFail);
            Record(it, r == 1, "done", (r == 1 ? "ok: " : r == 0 ? "not ok: " : "couldn't check: ") + d);
            return true;
        }
        // verify-fails (or the check after our own reload): act only when the check stays false
        string detail;
        int ok = Check(it.Verify, out detail);
        if (ok == 1)
        {
            Record(it, true, it.Recheck ? "rechecked" : "done", (it.Recheck ? "ok after the reload: " : "not needed: ") + detail);
            return true;
        }
        if (since < it.Wait) return false;
        if (ok < 0) { Record(it, false, "done", "couldn't check: " + detail); return true; }
        if (it.Recheck || it.Action == "check")
        {
            if (it.OnFail.Length > 0) Feed(it.OnFail);
            Record(it, false, it.Recheck ? "rechecked" : "done", (it.Recheck ? "still not ok after the reload: " : "not ok: ") + detail);
            return true;
        }
        it.Due = true;   // reload-scripts, once everything else is done
        return true;
    }

    List<SetupItem> PendingSetup()
    {
        List<SetupItem> list = new List<SetupItem>();
        foreach (Dictionary<string, object> m in Items(model, "setup"))
        {
            string mod = Str(m, "mod"), stamp = Str(m, "stamp");
            List<object> acts = Get(m, "actions") as List<object>;
            if (acts == null) continue;
            for (int i = 0; i < acts.Count; i++)
            {
                Dictionary<string, object> a = acts[i] as Dictionary<string, object>;
                if (a == null) continue;
                SetupItem it = new SetupItem();
                it.Mod = mod;
                it.Stamp = stamp;
                it.Action = Str(a, "action");
                it.When = Str(a, "when").Length == 0 ? "first-load" : Str(a, "when");
                it.OnFail = Str(a, "onFail");
                it.Verify = Get(a, "verify") as Dictionary<string, object>;
                it.Wait = it.Verify != null && Get(it.Verify, "withinSeconds") is double ? Num(it.Verify, "withinSeconds") : DefaultWait;
                it.DoneKey = mod + "#" + i.ToString(Inv);
                Dictionary<string, object> d = setupDone == null ? null : Get(setupDone, it.DoneKey) as Dictionary<string, object>;
                if (!setupForce && d != null)
                {
                    if (it.When != "verify-fails" && Str(d, "stamp") == stamp) continue;
                    if (it.When == "verify-fails" && Str(d, "process") == processKey)
                    {
                        if (Str(d, "stage") != "acted") continue;
                        it.Recheck = true;
                    }
                }
                list.Add(it);
            }
        }
        return list;
    }

    void Record(SetupItem it, bool ok, string stage, string message)
    {
        Dictionary<string, object> d = new Dictionary<string, object>();
        d["stamp"] = it.Stamp;
        d["process"] = processKey;
        d["stage"] = stage;
        d["at"] = DateTime.UtcNow.ToString("s", Inv) + "Z";
        d["ok"] = ok;
        d["message"] = message;
        if (setupDone == null) setupDone = new Dictionary<string, object>();
        setupDone[it.DoneKey] = d;
        Dictionary<string, object> r = new Dictionary<string, object>();
        r["action"] = it.Action;
        r["ok"] = ok;
        r["message"] = message;
        if (!setupResults.ContainsKey(it.Mod)) setupResults[it.Mod] = new List<object>();
        setupResults[it.Mod].Add(r);
        setupStamps[it.Mod] = it.Stamp;
    }

    void ReportSetup()
    {
        foreach (KeyValuePair<string, List<object>> kv in setupResults)
        {
            Dictionary<string, object> f = new Dictionary<string, object>();
            f["mod"] = kv.Key;
            f["stamp"] = setupStamps.ContainsKey(kv.Key) ? setupStamps[kv.Key] : "";
            f["results"] = kv.Value;
            Request("setup", f);
        }
        setupResults.Clear();
    }

    void LoadSetupDone()
    {
        setupDone = new Dictionary<string, object>();
        try
        {
            if (!File.Exists(setupDonePath)) return;
            Dictionary<string, object> d = LeonidaJson.Parse(File.ReadAllText(setupDonePath, Encoding.UTF8)) as Dictionary<string, object>;
            Dictionary<string, object> done = d == null ? null : Get(d, "done") as Dictionary<string, object>;
            if (done != null) setupDone = done;
        }
        catch (Exception) { }
    }

    void SaveSetupDone()
    {
        try
        {
            Directory.CreateDirectory(bridgeDir);
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["schema"] = 1.0;
            d["menu"] = Version;
            d["done"] = setupDone ?? new Dictionary<string, object>();
            string tmp = setupDonePath + ".tmp";
            File.WriteAllText(tmp, LeonidaJson.Write(d), new UTF8Encoding(false));
            if (File.Exists(setupDonePath)) File.Delete(setupDonePath);
            File.Move(tmp, setupDonePath);
        }
        catch (Exception ex) { Note("Could not save the in-game setup record: " + ex.Message); }
    }

    void RunSetupAgain()
    {
        setupForce = true;
        setupFinished = false;
        setupQueue = null;
        readySince = DateTime.UtcNow.AddSeconds(-600);   // every wait is over: act now
        Close();
        Note("Running the in-game setup again");
    }

    // ------------------------------------------------------------------------------------------- in-game checks
    // 1 = ok, 0 = not ok, -1 = can't be told here. Read-only: nothing in the game or on disk changes.
    int Check(Dictionary<string, object> c, out string detail)
    {
        detail = "";
        if (c == null) { detail = "no check given"; return -1; }
        string kind = Str(c, "kind");
        detail = Describe(c);
        try
        {
            if (kind == "dlc") return Function.Call<bool>(Hash.IS_DLC_PRESENT, Function.Call<int>(Hash.GET_HASH_KEY, Str(c, "name"))) ? 1 : 0;
            if (kind == "ipl") return Function.Call<bool>(Hash.IS_IPL_ACTIVE, Str(c, "name")) ? 1 : 0;
            if (kind == "native") return CheckNative(c, ref detail);
            if (kind == "asi") return File.Exists(GamePath(Str(c, "name"))) ? 1 : 0;
            if (kind == "script" || kind == "file")
            {
                string rel = Str(c, kind == "script" ? "file" : "path");
                return File.Exists(GamePath(rel)) || Directory.Exists(GamePath(rel)) ? 1 : 0;
            }
            if (kind == "log") return CheckLog(c, ref detail);
        }
        catch (Exception ex) { detail += " (" + ex.GetType().Name + ")"; return -1; }
        detail += " (checked by Leonida, not in game)";
        return -1;
    }

    int CheckNative(Dictionary<string, object> c, ref string detail)
    {
        string name = Str(c, "name");
        if (!(name.StartsWith("GET_") || name.StartsWith("IS_") || name.StartsWith("HAS_"))) { detail += " (only read-only natives)"; return -1; }
        Hash h;
        if (!Enum.TryParse<Hash>(name, out h)) { detail += " (not in Script Hook V .NET's list)"; return -1; }
        int v = Function.Call<int>(h);
        object want = Get(c, "equals");
        detail = name + " = " + v.ToString(Inv);
        if (want is bool) return ((v != 0) == (bool)want) ? 1 : 0;
        if (want is double) return v == (int)(double)want ? 1 : 0;
        return 1;
    }

    int CheckLog(Dictionary<string, object> c, ref string detail)
    {
        string rel = Str(c, "file"), want = Str(c, "contains");
        string path = GamePath(rel);
        if (!File.Exists(path)) { detail = rel + " isn't there"; return 0; }
        if (File.GetLastWriteTimeUtc(path) < gameStartUtc.AddSeconds(-2)) { detail = rel + " is from an earlier game start"; return 0; }
        if (want.Length == 0) return 1;
        string text;
        using (FileStream fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
        using (StreamReader sr = new StreamReader(fs, Encoding.UTF8, true))
            text = sr.ReadToEnd();
        if (text.Contains(want)) return 1;
        detail = rel + " has no '" + want + "' yet";
        return 0;
    }

    string GamePath(string rel)
    {
        return Path.Combine(gameDir, rel.Replace('/', Path.DirectorySeparatorChar));
    }

    static string Describe(Dictionary<string, object> c)
    {
        string kind = Str(c, "kind");
        if (kind == "dlc") return "DLC pack " + Str(c, "name") + " present";
        if (kind == "ipl") return "IPL " + Str(c, "name") + " active";
        if (kind == "native") return Str(c, "name") + (Get(c, "equals") != null ? " = " + AsText(Get(c, "equals")) : "");
        if (kind == "log") return Str(c, "file") + (Str(c, "contains").Length > 0 ? ": '" + Str(c, "contains") + "'" : " written");
        if (kind == "asi") return Str(c, "name") + " in the game folder";
        if (kind == "script") return Str(c, "file") + " in place";
        if (kind == "file") return Str(c, "path") + " present";
        return kind;
    }

    // The self-test's last stage: every installed mod's checks from the model, retried until all pass or time is up.
    bool InGameChecksDone()
    {
        if (checksStart == DateTime.MinValue) checksStart = DateTime.UtcNow;
        if (!setupFinished && (DateTime.UtcNow - checksStart).TotalSeconds < ChecksWaitSetup) return false;
        if (checksAt == DateTime.MinValue) checksAt = DateTime.UtcNow;
        bool timeUp = (DateTime.UtcNow - checksAt).TotalSeconds >= ChecksTimeout;
        if ((DateTime.UtcNow - checksRun).TotalSeconds < 1 && !timeUp) return false;
        checksRun = DateTime.UtcNow;
        checkResults.Clear();
        checksAllOk = true;
        foreach (Dictionary<string, object> m in Items(model, "checks"))
        {
            List<object> rs = new List<object>();
            foreach (Dictionary<string, object> c in Items(m, "verify"))
            {
                string d;
                int r = Check(c, out d);
                Dictionary<string, object> o = new Dictionary<string, object>();
                o["kind"] = Str(c, "kind");
                o["what"] = Describe(c);
                if (r >= 0) o["ok"] = r == 1;
                o["detail"] = d;
                rs.Add(o);
                if (r == 0) checksAllOk = false;
            }
            checkResults[Str(m, "mod")] = rs;
        }
        return checksAllOk || timeUp;
    }

    static void Feed(string text)
    {
        try
        {
            Function.Call(Hash.BEGIN_TEXT_COMMAND_THEFEED_POST, "STRING");
            AddText("Leonida: " + Clean(text));
            Function.Call(Hash.END_TEXT_COMMAND_THEFEED_POST_TICKER, false, true);
        }
        catch (Exception) { }
    }

    // "Insert", "F5", "Ctrl+F12": the modifier keys first, then the key; null when a part isn't a key
    static List<Keys> ParseKeys(string text)
    {
        List<Keys> keys = new List<Keys>();
        foreach (string part in text.Split('+'))
        {
            string p = part.Trim().ToLowerInvariant();
            if (p == "ctrl" || p == "control") { keys.Add(Keys.ControlKey); continue; }
            if (p == "shift") { keys.Add(Keys.ShiftKey); continue; }
            if (p == "alt") { keys.Add(Keys.Menu); continue; }
            try { keys.Add((Keys)Enum.Parse(typeof(Keys), part.Trim(), true)); }
            catch (Exception) { return null; }
        }
        return keys.Count == 0 ? null : keys;
    }

    static void PressKeys(List<Keys> keys)
    {
        foreach (Keys k in keys) keybd_event((byte)k, 0, 0, UIntPtr.Zero);
        for (int i = keys.Count - 1; i >= 0; i--) keybd_event((byte)keys[i], 0, 2, UIntPtr.Zero);   // KEYEVENTF_KEYUP
    }

    // ------------------------------------------------------------------------------------------- events
    void OnKeyDown(object sender, KeyEventArgs e)
    {
        if (e.KeyCode != openKey || (e.Modifiers & (Keys.Control | Keys.Shift | Keys.Alt)) != openModifier) return;
        if (Function.Call<bool>(Hash.NETWORK_IS_SESSION_STARTED)) return;   // story mode only
        if (open) Close(); else Open();
    }

    void OnPhoneAnswered(object contact)
    {
        try { contact.GetType().GetMethod("EndCall").Invoke(contact, null); }
        catch (Exception) { }
        Open();
    }

    void OnAborted(object sender, EventArgs e)
    {
        open = false;
    }

    void OnTick(object sender, EventArgs e)
    {
        if (firstTick == DateTime.MinValue) { firstTick = DateTime.UtcNow; SetupPhone(); }
        if (phoneUpdate != null)
        {
            try { phoneUpdate.Invoke(phone, null); }
            catch (Exception) { phoneUpdate = null; phoneState = "stopped"; }
        }
        try { SetupTick(); }
        catch (Exception ex) { setupFinished = true; setupState = "stopped: " + ex.Message; }
        if (selfTest) { SelfTestTick(); return; }
        if (!open) return;
        if (Function.Call<bool>(Hash.IS_PAUSE_MENU_ACTIVE)) return;
        ReadModel(false);
        HandleInput();
        if (open) Draw();
    }

    void HandleInput()
    {
        Function.Call(Hash.DISABLE_ALL_CONTROL_ACTIONS, 0);
        Function.Call(Hash.DISABLE_CONTROL_ACTION, 2, 199, true);   // INPUT_FRONTEND_PAUSE
        Function.Call(Hash.DISABLE_CONTROL_ACTION, 2, 200, true);   // INPUT_FRONTEND_PAUSE_ALTERNATE (Esc)
        if (stack.Count == 0) return;
        Page p = stack[stack.Count - 1];
        if (Pressed(172)) Move(p, -1);
        if (Pressed(173)) Move(p, 1);
        Row row = p.Rows.Count > 0 && p.Sel < p.Rows.Count ? p.Rows[p.Sel] : null;
        if (Pressed(174) && row != null && row.Change != null) { row.Change(-1); Sound("NAV_LEFT_RIGHT"); }
        if (Pressed(175) && row != null && row.Change != null) { row.Change(1); Sound("NAV_LEFT_RIGHT"); }
        if (Pressed(201) && row != null && row.Activate != null) row.Activate();
        if (Pressed(202) || Pressed(200))
        {
            stack.RemoveAt(stack.Count - 1);
            if (stack.Count == 0) Close(); else Sound("BACK");
        }
    }

    static bool Pressed(int control)
    {
        return Function.Call<bool>(Hash.IS_DISABLED_CONTROL_JUST_PRESSED, 2, control)
            || Function.Call<bool>(Hash.IS_CONTROL_JUST_PRESSED, 2, control);
    }

    void Move(Page p, int step)
    {
        if (p.Rows.Count == 0) return;
        p.Sel = (p.Sel + step + p.Rows.Count) % p.Rows.Count;
        if (p.Sel < p.Top) p.Top = p.Sel;
        if (p.Sel >= p.Top + VisibleRows) p.Top = p.Sel - VisibleRows + 1;
        Sound("NAV_UP_DOWN");
    }

    // ------------------------------------------------------------------------------------------- drawing
    void Draw()
    {
        if (stack.Count == 0) return;
        Page p = stack[stack.Count - 1];
        int shown = Math.Min(VisibleRows, Math.Max(p.Rows.Count - p.Top, 0));
        float avail = PanelW - 2 * Pad;
        Func<string, float> rowW = delegate(string t) { return TextWidth(t, RowScale); };
        // lay the rows out first: a row too long for its line is shortened there, and the selected one is shown in
        // full in the bottom box (text meant to be read is wrapped when the page is built, so it always fits)
        string[] lefts = new string[shown], rights = new string[shown];
        string full = null;
        for (int i = 0; i < shown; i++)
        {
            Row row = p.Rows[p.Top + i];
            string l = Clean(row.Text), rt = Clean(row.Right);
            if (LeonidaLayout.FitPair(l, rt, avail, Gap, rowW, out lefts[i], out rights[i]) && p.Top + i == p.Sel)
                full = rt.Length > 0 ? l + ": " + rt : l;
        }
        string msg = DateTime.UtcNow < noteUntil ? note
            : full ?? "Arrows: move   Left/Right: change   Enter: choose   Backspace: back";
        List<string> box = LeonidaLayout.Wrap(Clean(msg), avail, delegate(string t) { return TextWidth(t, BoxScale); });
        if (box.Count == 0) box.Add("");
        if (box.Count > BoxLines) box.RemoveRange(BoxLines, box.Count - BoxLines);
        float boxH = RowH + LineH * (box.Count - 1);
        float h = RowH * (shown + 2) + boxH;
        float cx = PanelX + PanelW / 2;
        Rect(cx, TopY + h / 2, PanelW, h, 10, 10, 18, 215);
        Rect(cx, TopY + RowH / 2, PanelW, RowH, 255, 79, 139, 235);                // header, Leonida pink
        string title = stack.Count == 1 ? "LEONIDA V" : "LEONIDA V  " + Clean(p.Title.ToUpperInvariant());
        Text(title, PanelX + Pad, TopY + 0.003f, 0.38f, 255, 255, 255, 255, false);
        for (int i = 0; i < shown; i++)
        {
            int index = p.Top + i;
            Row row = p.Rows[index];
            float y = TopY + RowH * (i + 1);
            bool sel = index == p.Sel;
            if (sel) Rect(cx, y + RowH / 2, PanelW, RowH, 255, 193, 94, 225);
            int c = sel ? 10 : (row.Dim ? 150 : 235);
            int r = row.Warn && !sel ? 255 : c, g = row.Warn && !sel ? 120 : c, b = row.Warn && !sel ? 120 : c;
            Text(lefts[i], PanelX + Pad, y + 0.004f, RowScale, r, g, b, 255, false);
            if (rights[i].Length > 0) Text(rights[i], PanelX + PanelW - Pad, y + 0.004f, RowScale, r, g, b, 255, true);
        }
        float fy = TopY + RowH * (shown + 1);
        string foot = p.Rows.Count > VisibleRows ? (p.Sel + 1).ToString(Inv) + " / " + p.Rows.Count.ToString(Inv) + "   " : "";
        foot += Connected() ? "Leonida is running" : "Open Leonida to apply changes (or they apply next time it starts)";
        Text(foot, PanelX + Pad, fy + 0.004f, FootScale, 170, 170, 190, 255, false);
        Rect(cx, fy + RowH + boxH / 2, PanelW, boxH, 25, 25, 38, 225);
        for (int k = 0; k < box.Count; k++)
            Text(box[k], PanelX + Pad, fy + RowH + 0.004f + LineH * k, BoxScale, 255, 193, 94, 255, false);
    }

    // Text meant to be read: wrapped to the panel's width when the page is built.
    List<string> Wrap(string text)
    {
        return LeonidaLayout.Wrap(Clean(text ?? ""), PanelW - 2 * Pad, delegate(string t) { return TextWidth(t, RowScale); });
    }

    // Width on screen (0..1 of the screen width) as the game measures it; the estimate when the game can't.
    float TextWidth(string s, float scale)
    {
        string key = scale.ToString(Inv) + "|" + s;
        float w;
        if (widths.TryGetValue(key, out w)) return w;
        w = 0f;
        try
        {
            Function.Call(Hash.SET_TEXT_FONT, 4);
            Function.Call(Hash.SET_TEXT_SCALE, 0f, scale);
            Function.Call(Hash.BEGIN_TEXT_COMMAND_GET_SCREEN_WIDTH_OF_DISPLAY_TEXT, "STRING");
            AddText(s);
            w = Function.Call<float>(Hash.END_TEXT_COMMAND_GET_SCREEN_WIDTH_OF_DISPLAY_TEXT, true);
        }
        catch (Exception) { w = 0f; }
        if (!(w > 0f) || w > 2f) w = LeonidaLayout.Estimate(s, scale);
        if (widths.Count > 4000) widths.Clear();
        widths[key] = w;
        return w;
    }

    static void Rect(float x, float y, float w, float h, int r, int g, int b, int a)
    {
        Function.Call(Hash.DRAW_RECT, x, y, w, h, r, g, b, a, false);
    }

    static void Text(string s, float x, float y, float scale, int r, int g, int b, int a, bool right)
    {
        Function.Call(Hash.SET_TEXT_FONT, 4);
        Function.Call(Hash.SET_TEXT_SCALE, 0f, scale);
        Function.Call(Hash.SET_TEXT_COLOUR, r, g, b, a);
        if (right)
        {
            Function.Call(Hash.SET_TEXT_JUSTIFICATION, 2);
            Function.Call(Hash.SET_TEXT_WRAP, 0f, x);
        }
        Function.Call(Hash.BEGIN_TEXT_COMMAND_DISPLAY_TEXT, "STRING");
        AddText(s);
        Function.Call(Hash.END_TEXT_COMMAND_DISPLAY_TEXT, right ? 0f : x, y, 0);
    }

    static void AddText(string s)
    {
        for (int i = 0; i < s.Length; i += 90)
            Function.Call(Hash.ADD_TEXT_COMPONENT_SUBSTRING_PLAYER_NAME, s.Substring(i, Math.Min(90, s.Length - i)));
    }

    // ------------------------------------------------------------------------------------------- the phone
    void SetupPhone()
    {
        try
        {
            Assembly asm = null;
            foreach (Assembly a in AppDomain.CurrentDomain.GetAssemblies()) if (a.GetName().Name == "iFruitAddon2") asm = a;
            if (asm == null)
            {
                string dll = Path.Combine(scriptsDir, "iFruitAddon2.dll");
                if (!File.Exists(dll)) { phoneState = "no iFruitAddon2"; return; }
                asm = Assembly.LoadFrom(dll);
            }
            Type fruitType = asm.GetType("iFruitAddon2.CustomiFruit");
            Type contactType = asm.GetType("iFruitAddon2.iFruitContact");
            if (fruitType == null || contactType == null) { phoneState = "iFruitAddon2 without the expected types"; return; }
            object fruit = Activator.CreateInstance(fruitType);
            object contact = Activator.CreateInstance(contactType, new object[] { "Leonida" });
            EventInfo answered = contactType.GetEvent("Answered");
            MethodInfo handler = typeof(LeonidaMenu).GetMethod("OnPhoneAnswered", BindingFlags.NonPublic | BindingFlags.Instance);
            answered.AddEventHandler(contact, Delegate.CreateDelegate(answered.EventHandlerType, this, handler));
            SetProp(contact, "DialTimeout", 1000);
            SetProp(contact, "Active", true);
            object contacts = fruitType.GetProperty("Contacts").GetValue(fruit, null);
            contacts.GetType().GetMethod("Add").Invoke(contacts, new object[] { contact });
            phone = fruit;
            phoneUpdate = fruitType.GetMethod("Update", Type.EmptyTypes);
            phoneState = "call \"Leonida\"";
        }
        catch (Exception ex) { phoneState = "unavailable (" + ex.GetType().Name + ")"; }
    }

    static void SetProp(object target, string name, object value)
    {
        PropertyInfo p = target.GetType().GetProperty(name);
        if (p != null && p.CanWrite) p.SetValue(target, value, null);
    }

    // ------------------------------------------------------------------------------------------- self-test
    void SelfTestTick()
    {
        // wait for story mode: no loading screen and a few seconds in (it builds pages, so the game must be up)
        if ((DateTime.UtcNow - firstTick).TotalSeconds < 8 || Function.Call<bool>(Hash.GET_IS_LOADING_SCREEN_ACTIVE)) return;
        if (selfStage < 0)
        {
            ReadModel(true);
            Open();
            Dictionary<string, object> f = new Dictionary<string, object>();
            f["note"] = "menu self-test";
            pingId = Request("ping", f);
            pingAt = DateTime.UtcNow;
            selfStage = 0;
        }
        List<Row> root = stack.Count > 0 ? stack[0].Rows : new List<Row>();
        if (selfStage < root.Count)
        {
            // open each top-level page and draw it for one tick
            while (stack.Count > 1) stack.RemoveAt(stack.Count - 1);
            Row r = root[selfStage];
            if (r.Activate != null) r.Activate();
            Page p = stack[stack.Count - 1];
            selfPages[p.Title] = p.Rows.Count;
            // one level deeper for the first item that opens a page (a mod, a help text)
            if (p.Rows.Count > 0 && p.Rows[0].Activate != null && (p.Title == "Mods" || p.Title == "Help"))
            {
                p.Rows[0].Activate();
                selfPages[p.Title + " > " + stack[stack.Count - 1].Title] = stack[stack.Count - 1].Rows.Count;
            }
            try { Draw(); selfDrawn++; }
            catch (Exception ex) { selfErrors.Add("draw " + p.Title + ": " + ex.Message); }
            selfStage++;
            return;
        }
        // the queue both ways: wait (a while) for Leonida's answer to the ping
        if (selfAnswer == null)
        {
            ReadModel(true);
            string a = AnswerFor(pingId);
            if (a == null && (DateTime.UtcNow - pingAt).TotalSeconds < 30) return;
            selfAnswer = a ?? "";
        }
        string answer = selfAnswer.Length == 0 ? null : selfAnswer;
        // the mods' in-game checks, once the in-game setup has settled
        if (!InGameChecksDone()) return;
        Dictionary<string, object> rep = new Dictionary<string, object>();
        rep["menu"] = Version;
        rep["ok"] = selfErrors.Count == 0 && model != null;
        rep["model"] = model != null;
        rep["connected"] = Connected();
        Dictionary<string, object> pages = new Dictionary<string, object>();
        foreach (KeyValuePair<string, int> kv in selfPages) pages[kv.Key] = (double)kv.Value;
        rep["pages"] = pages;
        rep["drawn"] = (double)selfDrawn;
        rep["ping"] = pingId;
        rep["ping_answer"] = answer == null ? "" : answer;
        rep["phone"] = phoneState;
        rep["key"] = KeyText();
        List<object> errs = new List<object>();
        foreach (string s in selfErrors) errs.Add(s);
        rep["errors"] = errs;
        Dictionary<string, object> ingame = new Dictionary<string, object>();
        foreach (KeyValuePair<string, List<object>> kv in checkResults) ingame[kv.Key] = kv.Value;
        rep["ingame"] = ingame;
        rep["setup"] = setupState;
        try
        {
            File.WriteAllText(reportPath, LeonidaJson.Write(rep), new UTF8Encoding(false));
            if (File.Exists(flagPath)) File.Delete(flagPath);
        }
        catch (Exception) { }
        selfTest = false;
        Close();
    }

    // ------------------------------------------------------------------------------------------- helpers
    string KeyText()
    {
        string m = "";
        if ((openModifier & Keys.Control) != 0) m += "Ctrl+";
        if ((openModifier & Keys.Shift) != 0) m += "Shift+";
        if ((openModifier & Keys.Alt) != 0) m += "Alt+";
        return m + openKey.ToString();
    }

    static Row Info(string text, string right)
    {
        Row r = new Row();
        r.Text = text;
        r.Right = right;
        return r;
    }

    static object Get(Dictionary<string, object> d, string key)
    {
        object v;
        return d != null && d.TryGetValue(key, out v) ? v : null;
    }

    static string AsText(object v)
    {
        if (v == null) return "";
        if (v is bool) return (bool)v ? "true" : "false";
        if (v is double) return ((double)v).ToString(Inv);
        return v.ToString();
    }

    static string Str(Dictionary<string, object> d, string key) { return AsText(Get(d, key)); }

    static bool Bool(Dictionary<string, object> d, string key)
    {
        object v = Get(d, key);
        return v is bool && (bool)v;
    }

    static double Num(Dictionary<string, object> d, string key)
    {
        object v = Get(d, key);
        return v is double ? (double)v : 0;
    }

    static List<Dictionary<string, object>> Items(Dictionary<string, object> d, string key)
    {
        List<Dictionary<string, object>> out1 = new List<Dictionary<string, object>>();
        List<object> list = Get(d, key) as List<object>;
        if (list != null) foreach (object o in list) { Dictionary<string, object> x = o as Dictionary<string, object>; if (x != null) out1.Add(x); }
        return out1;
    }

    static string Clean(string s) { return s.Replace("~", "-"); }   // "~" starts GTA's text formatting codes
}

// Text layout by width on screen (0..1 of the screen width), with the measure passed in: the game's own text-width
// native in the menu, the estimate in tests. Pure code, so tests/test_menu.py runs it without the game.
public static class LeonidaLayout
{
    // GTA draws (and measures) only the FIRST text component of a "STRING" text command, and a component holds at
    // most 99 characters; the menu adds them 90 at a time. So no line may be longer than one component: a 126-letter
    // note was measured and drawn as its first 90 letters ("...adds or removes the") and the rest was lost.
    public const int MaxChars = 90;

    // The measure, with every text longer than one component counted as too wide.
    static Func<string, float> Capped(Func<string, float> width)
    {
        return delegate(string t) { return t.Length > MaxChars ? float.MaxValue : width(t); };
    }

    // Word wrap: every line fits in max and in one text component; no word is cut unless a single word is wider
    // than a whole line.
    public static List<string> Wrap(string text, float max, Func<string, float> measure)
    {
        Func<string, float> width = Capped(measure);
        List<string> lines = new List<string>();
        if (text == null) return lines;
        foreach (string para in text.Replace("\r", "").Split('\n'))
        {
            string line = "";
            foreach (string w in para.Split(' '))
            {
                if (w.Length == 0) continue;
                string word = w;
                string tryLine = line.Length == 0 ? word : line + " " + word;
                if (width(tryLine) <= max) { line = tryLine; continue; }
                if (line.Length > 0) lines.Add(line);
                while (word.Length > 1 && width(word) > max)   // a word wider than the panel: break it
                {
                    int n = Longest(word, max, width, "");
                    lines.Add(word.Substring(0, n));
                    word = word.Substring(n);
                }
                line = word;
            }
            if (line.Length > 0) lines.Add(line);
        }
        return lines;
    }

    // Shorten to fit max, ending in "...". Only for labels (a mod's name, a value), never for text meant to be read.
    public static string Fit(string s, float max, Func<string, float> measure)
    {
        Func<string, float> width = Capped(measure);
        if (width(s) <= max) return s;
        int n = Longest(s, max, width, "...");
        return s.Substring(0, n).TrimEnd() + "...";
    }

    // A row's left and right text on one line, the gap between them. Returns true when something was shortened:
    // the shorter side (a key name, "on") keeps its full text and the longer side gets what's left.
    public static bool FitPair(string left, string right, float max, float gap, Func<string, float> measure,
                               out string l, out string r)
    {
        Func<string, float> width = Capped(measure);
        l = left;
        r = right;
        float lw = width(left), rw = right.Length > 0 ? width(right) : 0f;
        if (right.Length == 0)
        {
            if (lw <= max) return false;
            l = Fit(left, max, width);
            return true;
        }
        if (lw + gap + rw <= max) return false;
        float least = max * 0.3f;
        if (lw <= rw)
        {
            r = Fit(right, Math.Max(max - gap - lw, least), width);
            if (lw + gap + width(r) > max) l = Fit(left, Math.Max(max - gap - width(r), 0f), width);
        }
        else
        {
            l = Fit(left, Math.Max(max - gap - rw, least), width);
            if (width(l) + gap + rw > max) r = Fit(right, Math.Max(max - gap - width(l), 0f), width);
        }
        return true;
    }

    // The width of text in GTA's condensed menu font (font 4), from screenshots at 1920x1080: about 0.0082 of the
    // screen per character per 1.0 of text scale; a little more here so the estimate errs on the side of wrapping.
    public static float Estimate(string s, float scale)
    {
        float units = 0f;
        foreach (char ch in s)
        {
            if (ch == ' ') units += 0.6f;
            else if (".,:;'!|il1()[]".IndexOf(ch) >= 0) units += 0.55f;
            else if (char.IsUpper(ch) || ch == 'm' || ch == 'w' || ch == '@' || ch == '%') units += 1.3f;
            else units += 1f;
        }
        return units * 0.0088f * scale;
    }

    static int Longest(string s, float max, Func<string, float> width, string tail)
    {
        int lo = 1, hi = s.Length;
        while (lo < hi)
        {
            int mid = (lo + hi + 1) / 2;
            if (width(s.Substring(0, mid).TrimEnd() + tail) <= max) lo = mid; else hi = mid - 1;
        }
        return lo;
    }
}

// A small JSON reader/writer (no System.Web.Extensions in Script Hook V .NET's compiler references): objects ->
// Dictionary<string, object>, arrays -> List<object>, numbers -> double, true/false -> bool, null -> null.
public static class LeonidaJson
{
    public static object Parse(string s)
    {
        int i = 0;
        object v = Value(s, ref i);
        return v;
    }

    static void Skip(string s, ref int i) { while (i < s.Length && char.IsWhiteSpace(s[i])) i++; }

    static object Value(string s, ref int i)
    {
        Skip(s, ref i);
        if (i >= s.Length) throw new FormatException("end of JSON");
        char c = s[i];
        if (c == '{')
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            i++;
            Skip(s, ref i);
            if (i < s.Length && s[i] == '}') { i++; return d; }
            while (true)
            {
                Skip(s, ref i);
                string key = ReadString(s, ref i);
                Skip(s, ref i);
                if (i >= s.Length || s[i] != ':') throw new FormatException("':' expected");
                i++;
                d[key] = Value(s, ref i);
                Skip(s, ref i);
                if (i < s.Length && s[i] == ',') { i++; continue; }
                if (i < s.Length && s[i] == '}') { i++; return d; }
                throw new FormatException("',' or '}' expected");
            }
        }
        if (c == '[')
        {
            List<object> list = new List<object>();
            i++;
            Skip(s, ref i);
            if (i < s.Length && s[i] == ']') { i++; return list; }
            while (true)
            {
                list.Add(Value(s, ref i));
                Skip(s, ref i);
                if (i < s.Length && s[i] == ',') { i++; continue; }
                if (i < s.Length && s[i] == ']') { i++; return list; }
                throw new FormatException("',' or ']' expected");
            }
        }
        if (c == '"') return ReadString(s, ref i);
        if (s.Substring(i).StartsWith("true")) { i += 4; return true; }
        if (s.Substring(i).StartsWith("false")) { i += 5; return false; }
        if (s.Substring(i).StartsWith("null")) { i += 4; return null; }
        int start = i;
        while (i < s.Length && "+-0123456789.eE".IndexOf(s[i]) >= 0) i++;
        if (i == start) throw new FormatException("unexpected '" + c + "'");
        return double.Parse(s.Substring(start, i - start), NumberStyles.Float, CultureInfo.InvariantCulture);
    }

    static string ReadString(string s, ref int i)
    {
        if (s[i] != '"') throw new FormatException("string expected");
        i++;
        StringBuilder sb = new StringBuilder();
        while (i < s.Length && s[i] != '"')
        {
            char c = s[i++];
            if (c != '\\') { sb.Append(c); continue; }
            char e = s[i++];
            if (e == 'n') sb.Append('\n');
            else if (e == 't') sb.Append('\t');
            else if (e == 'r') sb.Append('\r');
            else if (e == 'b') sb.Append('\b');
            else if (e == 'f') sb.Append('\f');
            else if (e == 'u') { sb.Append((char)Convert.ToInt32(s.Substring(i, 4), 16)); i += 4; }
            else sb.Append(e);
        }
        i++;
        return sb.ToString();
    }

    public static string Write(object v)
    {
        StringBuilder sb = new StringBuilder();
        Emit(v, sb);
        return sb.ToString();
    }

    static void Emit(object v, StringBuilder sb)
    {
        if (v == null) { sb.Append("null"); return; }
        if (v is bool) { sb.Append((bool)v ? "true" : "false"); return; }
        if (v is double || v is int || v is float || v is long) { sb.Append(Convert.ToDouble(v).ToString("R", CultureInfo.InvariantCulture)); return; }
        Dictionary<string, object> d = v as Dictionary<string, object>;
        if (d != null)
        {
            sb.Append('{');
            bool first = true;
            foreach (KeyValuePair<string, object> kv in d)
            {
                if (!first) sb.Append(',');
                first = false;
                Quote(kv.Key, sb);
                sb.Append(':');
                Emit(kv.Value, sb);
            }
            sb.Append('}');
            return;
        }
        List<object> list = v as List<object>;
        if (list != null)
        {
            sb.Append('[');
            for (int i = 0; i < list.Count; i++) { if (i > 0) sb.Append(','); Emit(list[i], sb); }
            sb.Append(']');
            return;
        }
        Quote(v.ToString(), sb);
    }

    static void Quote(string s, StringBuilder sb)
    {
        sb.Append('"');
        foreach (char c in s)
        {
            if (c == '"') sb.Append("\\\"");
            else if (c == '\\') sb.Append("\\\\");
            else if (c == '\n') sb.Append("\\n");
            else if (c == '\r') sb.Append("\\r");
            else if (c == '\t') sb.Append("\\t");
            else if (c < ' ') sb.Append("\\u" + ((int)c).ToString("x4"));
            else sb.Append(c);
        }
        sb.Append('"');
    }
}
