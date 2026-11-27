// C# 5 only (SHVDN's compiler): Script Hook V .NET compiles .cs scripts with the C# 5 rules, so no exception
// filters (catch ... when), string interpolation ($""), "?.", nameof, expression-bodied members or out variables.
// tests/test_probe.py and build/check_probe.py compile it with csc -langversion:5 to catch them.
//
// Leonida in-game probe (Script Hook V .NET, API v3). `leonida playtest --deep` copies it into scripts\ as
// LeonidaProbe.3.cs (the ".3" makes Script Hook V .NET compile it for API v3) and removes it after the run. It only
// reads game state, spawns one test car next to the player for a moment and deletes it again, and writes
// LeonidaProbe.log in the game folder. Story mode only.
//
// Rules that keep it alive (Script Hook V .NET Enhanced aborts a script whose tick takes too long, "Blocking
// script!", and since API 3.7 native calls don't reset that timer):
//   - no waiting inside a tick: no Model.Request(timeout), Wait() or Yield(); a model is requested once per tick
//     with REQUEST_MODEL and checked with HAS_MODEL_LOADED on the next ones;
//   - every stage has its own timeout, and the whole probe has a deadline;
//   - one heartbeat line per tick (every tick at first and during the car checks, then every 8th) with the raw
//     gate values, and an "hb" line after each native call / value read, so a probe that
//     waits forever says what it waits for; an abort from outside is logged too.
// Leonida fills in the pack list and the test car (the two placeholders below) before copying it.
//
// Interiors (mods.json verify kind "interior"): after the car check, the player is moved to each interior's x, y and
// GET_INTERIOR_AT_COORDS looks for it between zMin and zMax ("interior.<i>=<id> ready=<bool>"); then back home.
// Stress mode (`leonida playtest --stress police|drive`, Leonida fills in Stress and StressMinutes): after the checks,
// the probe keeps the game busy for StressMinutes, story mode only, with public natives:
//   police: the player is moved to the Vinewood Hills (-800, 1424), gets a pistol, is made invincible (so the fight
//           lasts) and gets 3 wanted stars, kept at 3, and is told to fight back; at the end the wanted level is
//           cleared and the player is normal again;
//   drive:  a fast car with the player at the wheel (invincible) drives a long route round the map (the city, the
//           airport, Sandy Shores, Paleto Bay) for the streaming; the car is deleted at the end.
// A "stress" heartbeat line every 15 s says where the player is, the wanted level and the health. Nothing is saved:
// the game's own autosave is not triggered by any of this.
using System;
using System.Globalization;
using System.IO;
using GTA;
using GTA.Math;
using GTA.Native;

public class LeonidaProbe : Script
{
    static readonly string[] Packs = { /*PACKS*/ };
    static readonly string[] Interiors = { /*INTERIORS*/ };  // "name|x|y|zMin|zMax" (mods.json verify kind "interior")
    const double InteriorTimeout = 20; // per interior: waiting for its map to stream in
    const string TestCar = "/*CAR*/";
    const double ReadySeconds = 5;     // the player has had control this long
    const double ReadyTimeout = 180;   // waiting for control (then the checks run anyway if the player ped exists)
    const double ModelTimeout = 20;    // waiting for the test car's model
    const double Deadline = 300;       // the whole probe, from its first tick (plus the stress minutes)
    const string Stress = "/*STRESS*/";                    // "", "police" or "drive"
    const double StressMinutes = /*STRESSMIN*/0;
    const string StressCar = "zentorno";                   // a fast base-game car for the drive
    static readonly float[] Route = {                      // x, y, z waypoints round the map (drive)
        -1034f, -2733f, 13.8f,   1692f, 3586f, 35.4f,   -235f, 6283f, 31.4f,   -1610f, 4780f, 54f,   229f, -880f, 30f };

    readonly string logPath;
    readonly CultureInfo inv = CultureInfo.InvariantCulture;
    DateTime firstTick = DateTime.MinValue, stageAt = DateTime.UtcNow, readySince = DateTime.MinValue;
    int stage, ticks, modelHash;
    Vehicle car;
    bool done;
    // interiors
    int interiorIdx;
    bool interiorsDone, homeSaved;
    Vector3 home;
    // stress
    Vehicle stressCar;
    int stressModel, waypoint;
    bool stressOn;
    DateTime stressStart, lastBeat, lastOrder;

    public LeonidaProbe()
    {
        logPath = Path.Combine(Directory.GetCurrentDirectory(), "LeonidaProbe.log");
        File.WriteAllText(logPath, "START " + Now() + " packs=" + Packs.Length + " car=" + TestCar + Environment.NewLine);
        Interval = 250;
        Tick += OnTick;
        Aborted += OnAborted;
    }

    string Now() { return DateTime.Now.ToString("HH:mm:ss.fff", inv); }

    void W(string line)
    {
        try { File.AppendAllText(logPath, line + Environment.NewLine); } catch { }
    }

    void Field(string name, float value)
    {
        W("handling." + name + "=" + value.ToString("R", inv));
    }

    void Stage(int next, string why)
    {
        stage = next;
        stageAt = DateTime.UtcNow;
        W("stage=" + next + " " + why);
    }

    double InStage { get { return (DateTime.UtcNow - stageAt).TotalSeconds; } }

    void OnAborted(object sender, EventArgs e)
    {
        if (!done) W("ABORTED stage=" + stage + " ticks=" + ticks + " " + Now());
        Cleanup();
    }

    void Cleanup()
    {
        StressCleanup();
        try { if (car != null && car.Exists()) car.Delete(); } catch { }
        try { if (modelHash != 0) Function.Call(Hash.SET_MODEL_AS_NO_LONGER_NEEDED, modelHash); } catch { }
        car = null;
    }

    void Finish(string why)
    {
        if (done) return;
        done = true;
        Cleanup();
        W("DONE " + why + " " + Now());
        Abort();
    }

    void OnTick(object sender, EventArgs e)
    {
        if (done) return;
        ticks++;
        try
        {
            if (firstTick == DateTime.MinValue) { firstTick = DateTime.UtcNow; stageAt = firstTick; }
            int ped = Function.Call<int>(Hash.PLAYER_PED_ID);
            bool exists = ped != 0 && Function.Call<bool>(Hash.DOES_ENTITY_EXIST, ped);
            bool playing = Function.Call<bool>(Hash.IS_PLAYER_PLAYING, Function.Call<int>(Hash.PLAYER_ID));
            bool loading = Function.Call<bool>(Hash.GET_IS_LOADING_SCREEN_ACTIVE);
            bool fadedIn = Function.Call<bool>(Hash.IS_SCREEN_FADED_IN);
            double age = (DateTime.UtcNow - firstTick).TotalSeconds;
            if (ticks <= 20 || ticks % 8 == 0 || stage >= 2)  // every tick once the car checks run
                W("TICK n=" + ticks + " t=" + age.ToString("0.0", inv) + " stage=" + stage + " ped=" + exists
                  + " playing=" + playing + " loading=" + loading + " fadedIn=" + fadedIn);
            if (age > Deadline + Interiors.Length * (InteriorTimeout + 5) + StressMinutes * 60 + (Stress.Length > 0 ? 120 : 0))
            { Finish("deadline stage=" + stage); return; }
            switch (stage)
            {
                case 0:  // wait until the player is in control for a few seconds
                    if (exists && playing && !loading)
                    {
                        if (readySince == DateTime.MinValue) readySince = DateTime.UtcNow;
                        if ((DateTime.UtcNow - readySince).TotalSeconds >= ReadySeconds) Stage(1, "ready");
                    }
                    else readySince = DateTime.MinValue;
                    if (stage == 0 && InStage > ReadyTimeout)
                    {
                        W("gate_timeout ped=" + exists + " playing=" + playing + " loading=" + loading);
                        if (exists) Stage(1, "going on without full control");
                        else Finish("no player ped");
                    }
                    break;
                case 1:  // DLC packs (setup2.xml nameHash)
                    foreach (string pack in Packs)
                        W("dlc." + pack + "=" + Function.Call<bool>(Hash.IS_DLC_PRESENT, Function.Call<int>(Hash.GET_HASH_KEY, pack)));
                    W("game_version=" + Game.FileVersion);
                    Stage(2, "dlc checked");
                    break;
                case 2:  // test car: request its model (no waiting here)
                    if (TestCar.Length == 0) { Stage(9, "no test car"); break; }
                    modelHash = Function.Call<int>(Hash.GET_HASH_KEY, TestCar);
                    W("hb GET_HASH_KEY " + TestCar);
                    bool inCd = Function.Call<bool>(Hash.IS_MODEL_IN_CDIMAGE, modelHash);
                    W("hb IS_MODEL_IN_CDIMAGE " + inCd);
                    bool isVeh = Function.Call<bool>(Hash.IS_MODEL_A_VEHICLE, modelHash);
                    W("car_model " + TestCar + " inCdImage=" + inCd + " vehicle=" + isVeh);
                    if (!inCd || !isVeh) { W("car_error=model not found: " + TestCar); Stage(9, "no car"); break; }
                    Function.Call(Hash.REQUEST_MODEL, modelHash);
                    W("hb REQUEST_MODEL");
                    Stage(3, "model requested");
                    break;
                case 3:  // model loaded? then spawn the car next to the player
                    bool loaded = Function.Call<bool>(Hash.HAS_MODEL_LOADED, modelHash);
                    if (!loaded)
                    {
                        Function.Call(Hash.REQUEST_MODEL, modelHash);
                        if (InStage > ModelTimeout) { W("car_error=model did not load in " + ModelTimeout + " s"); Stage(9, "no car"); }
                        break;
                    }
                    W("hb HAS_MODEL_LOADED true");
                    Ped p = Game.Player.Character;
                    Vector3 at = p.Position + p.ForwardVector * 8f + new Vector3(0f, 0f, 1f);
                    W("hb spawning at " + at.X.ToString("0.0", inv) + "," + at.Y.ToString("0.0", inv) + "," + at.Z.ToString("0.0", inv));
                    car = World.CreateVehicle(new Model(modelHash), at);  // the model is loaded: no waiting inside
                    W("car_spawned=" + (car != null && car.Exists()));
                    if (car == null || !car.Exists()) { W("car_error=could not spawn " + TestCar); Stage(9, "no car"); break; }
                    Stage(4, "car spawned");
                    break;
                case 4:  // handling as the game applied it (handling.meta of the active mods)
                    // Script Hook V .NET's own HandlingData (the CHandlingData in game memory). Not
                    // GET_VEHICLE_HANDLING_FLOAT (0x642FC12F): that's a FiveM native, single-player GTA V doesn't have it,
                    // and calling it stopped the probe's ticks without an error.
                    W("hb handling: reading HandlingData");
                    HandlingData h = car.HandlingData;
                    bool valid = h != null && h.IsValid;
                    W("hb handling: valid=" + valid);
                    if (!valid) { W("car_error=no handling data for " + TestCar); Cleanup(); Stage(9, "no handling"); break; }
                    Field("fMass", h.Mass);
                    Field("fInitialDriveForce", h.InitialDriveForce);
                    Field("fBrakeForce", h.BrakeForce);
                    Field("fTractionCurveMax", h.TractionCurveMax);
                    Cleanup();
                    W("hb car deleted");
                    Stage(9, "handling read");
                    break;
                case 9:  // the checks are done: interiors, then stress, or the end
                    if (Interiors.Length > 0 && !interiorsDone) Stage(10, "interiors");
                    else if (Stress == "police") Stage(20, "stress police");
                    else if (Stress == "drive") Stage(30, "stress drive");
                    else Finish("ok");
                    break;
                case 10: case 11:
                    CheckInteriors(exists);
                    break;
                case 20: case 21: case 22: case 23:
                    StressPolice(exists);
                    break;
                case 30: case 31: case 32: case 33:
                    StressDrive(exists);
                    break;
                default:
                    Finish("ok");
                    break;
            }
        }
        catch (System.Threading.ThreadAbortException)  // our own Abort() in Finish: not an error
        {
            throw;  // (SHVDN compiles .cs files with C# 5: no exception filters)
        }
        catch (Exception ex)
        {
            W("probe_error stage=" + stage + " " + ex.GetType().Name + ": " + ex.Message.Replace(Environment.NewLine, " "));
            Finish("error");
        }
    }

    // ------------------------------------------------------------------------------------------- interiors
    // For each interior: move the player to its x, y (the middle of its z range), let the area stream in, then look
    // for an interior between zMin and zMax with GET_INTERIOR_AT_COORDS; "interior.<i>=<id> ready=<bool>" (id 0 =
    // none there). The player goes back where they were at the end. Nothing is saved.
    void CheckInteriors(bool exists)
    {
        if (!exists) { interiorsDone = true; Stage(9, "interiors: no player ped"); return; }
        int ped = PlayerPed();
        if (interiorIdx >= Interiors.Length)
        {
            if (homeSaved) Function.Call(Hash.SET_ENTITY_COORDS, ped, home.X, home.Y, home.Z, false, false, false, true);
            interiorsDone = true;
            Stage(9, "interiors checked");
            return;
        }
        string[] f = Interiors[interiorIdx].Split('|');
        float x = float.Parse(f[1], inv), y = float.Parse(f[2], inv), zMin = float.Parse(f[3], inv), zMax = float.Parse(f[4], inv);
        float zMid = (zMin + zMax) / 2f;
        if (stage == 10)
        {
            if (!homeSaved) { home = Function.Call<Vector3>(Hash.GET_ENTITY_COORDS, ped, true); homeSaved = true; }
            Function.Call(Hash.REQUEST_COLLISION_AT_COORD, x, y, zMid);
            Function.Call(Hash.SET_ENTITY_COORDS, ped, x, y, zMid, false, false, false, true);
            W("interior_go " + interiorIdx + " " + f[0]);
            Stage(11, "interior " + f[0]);
            return;
        }
        Function.Call(Hash.REQUEST_COLLISION_AT_COORD, x, y, zMid);
        if (InStage < 3) return;
        int id = 0;
        for (float z = zMin; z <= zMax + 0.01f && id == 0; z += 1f)
            id = Function.Call<int>(Hash.GET_INTERIOR_AT_COORDS, x, y, z);
        bool ready = id != 0 && Function.Call<bool>(Hash.IS_INTERIOR_READY, id);
        if (ready || InStage > InteriorTimeout)
        {
            W("interior." + interiorIdx + "=" + id + " ready=" + ready + " name=" + f[0]);
            interiorIdx++;
            Stage(10, "interior done");
        }
    }

    // ------------------------------------------------------------------------------------------- stress
    int PlayerPed() { return Function.Call<int>(Hash.PLAYER_PED_ID); }

    int PlayerId() { return Function.Call<int>(Hash.PLAYER_ID); }

    string Where()
    {
        Vector3 v = Function.Call<Vector3>(Hash.GET_ENTITY_COORDS, PlayerPed(), true);
        return v.X.ToString("0", inv) + "," + v.Y.ToString("0", inv) + "," + v.Z.ToString("0", inv);
    }

    void Beat(string what)
    {
        if ((DateTime.UtcNow - lastBeat).TotalSeconds < 15) return;
        lastBeat = DateTime.UtcNow;
        int ped = PlayerPed();
        W("stress hb t=" + (DateTime.UtcNow - stressStart).TotalSeconds.ToString("0", inv) + " " + what
          + " pos=" + Where() + " wanted=" + Function.Call<int>(Hash.GET_PLAYER_WANTED_LEVEL, PlayerId())
          + " health=" + Function.Call<int>(Hash.GET_ENTITY_HEALTH, ped)
          + " dead=" + Function.Call<bool>(Hash.IS_ENTITY_DEAD, ped, false));
    }

    double StressAge { get { return (DateTime.UtcNow - stressStart).TotalSeconds; } }

    void StressPolice(bool exists)
    {
        if (!exists) { Finish("stress: no player ped"); return; }
        int ped = PlayerPed();
        switch (stage)
        {
            case 20:  // move to the Vinewood Hills (where the 25 Nov crash happened) and let the area load
                Function.Call(Hash.REQUEST_COLLISION_AT_COORD, -800f, 1424f, 243f);
                Function.Call(Hash.SET_ENTITY_COORDS, ped, -800f, 1424f, 243f, false, false, false, true);
                W("stress police moved pos=" + Where());
                Stage(21, "stress police: area loading");
                break;
            case 21:
                Function.Call(Hash.REQUEST_COLLISION_AT_COORD, -800f, 1424f, 243f);
                if (InStage < 6) break;
                Function.Call(Hash.GIVE_WEAPON_TO_PED, ped, Function.Call<int>(Hash.GET_HASH_KEY, "WEAPON_PISTOL"), 250, false, true);
                Function.Call(Hash.SET_PLAYER_INVINCIBLE, PlayerId(), true);
                Function.Call(Hash.SET_PLAYER_WANTED_LEVEL, PlayerId(), 3, false);
                Function.Call(Hash.SET_PLAYER_WANTED_LEVEL_NOW, PlayerId(), false);
                stressOn = true;
                stressStart = lastOrder = DateTime.UtcNow;
                lastBeat = DateTime.MinValue;
                W("stress police start minutes=" + StressMinutes.ToString(inv) + " pos=" + Where());
                Stage(22, "stress police: fighting");
                break;
            case 22:
                if (Function.Call<int>(Hash.GET_PLAYER_WANTED_LEVEL, PlayerId()) < 3)
                {
                    Function.Call(Hash.SET_PLAYER_WANTED_LEVEL, PlayerId(), 3, false);
                    Function.Call(Hash.SET_PLAYER_WANTED_LEVEL_NOW, PlayerId(), false);
                }
                if ((DateTime.UtcNow - lastOrder).TotalSeconds >= 20)
                {
                    lastOrder = DateTime.UtcNow;
                    Function.Call(Hash.TASK_COMBAT_HATED_TARGETS_AROUND_PED, ped, 120f, 0);
                }
                Beat("police");
                if (StressAge >= StressMinutes * 60) Stage(23, "stress police: time up");
                break;
            default:
                W("stress done police minutes=" + (StressAge / 60).ToString("0.0", inv) + " pos=" + Where());
                Finish("ok stress police");
                break;
        }
    }

    void StressDrive(bool exists)
    {
        if (!exists) { Finish("stress: no player ped"); return; }
        int ped = PlayerPed();
        switch (stage)
        {
            case 30:  // the car's model, requested without waiting inside the tick
                stressModel = Function.Call<int>(Hash.GET_HASH_KEY, StressCar);
                Function.Call(Hash.REQUEST_MODEL, stressModel);
                if (Function.Call<bool>(Hash.HAS_MODEL_LOADED, stressModel)) Stage(31, "stress drive: model loaded");
                else if (InStage > ModelTimeout) Finish("stress: car model " + StressCar + " didn't load");
                break;
            case 31:
                Ped p = Game.Player.Character;
                stressCar = World.CreateVehicle(new Model(stressModel), p.Position + p.ForwardVector * 4f, p.Heading);
                if (stressCar == null || !stressCar.Exists()) { Finish("stress: could not spawn " + StressCar); return; }
                Function.Call(Hash.SET_ENTITY_INVINCIBLE, stressCar, true);
                Function.Call(Hash.SET_PLAYER_INVINCIBLE, PlayerId(), true);
                Function.Call(Hash.SET_PED_INTO_VEHICLE, ped, stressCar, -1);
                stressOn = true;
                stressStart = DateTime.UtcNow;
                lastBeat = DateTime.MinValue;
                waypoint = -1;
                W("stress drive start minutes=" + StressMinutes.ToString(inv) + " car=" + StressCar + " pos=" + Where());
                Stage(32, "stress drive: driving");
                break;
            case 32:
                if (stressCar == null || !stressCar.Exists()) { Finish("stress: the car is gone"); return; }
                if (!Function.Call<bool>(Hash.IS_PED_IN_ANY_VEHICLE, ped, false)) Function.Call(Hash.SET_PED_INTO_VEHICLE, ped, stressCar, -1);
                Vector3 at = Function.Call<Vector3>(Hash.GET_ENTITY_COORDS, ped, true);
                bool next = waypoint < 0 || (DateTime.UtcNow - lastOrder).TotalSeconds > 360;
                if (waypoint >= 0)
                {
                    int i = waypoint * 3;
                    float dx = at.X - Route[i], dy = at.Y - Route[i + 1];
                    if (dx * dx + dy * dy < 60f * 60f) next = true;
                }
                if (next)
                {
                    waypoint = (waypoint + 1) % (Route.Length / 3);
                    int i = waypoint * 3;
                    lastOrder = DateTime.UtcNow;
                    // drive style 786603: normal traffic rules off for speed, avoids crashes into things
                    Function.Call(Hash.TASK_VEHICLE_DRIVE_TO_COORD_LONGRANGE, ped, stressCar, Route[i], Route[i + 1], Route[i + 2], 40f, 786603, 30f);
                    W("stress drive waypoint=" + waypoint + " pos=" + Where());
                }
                Beat("drive wp=" + waypoint);
                if (StressAge >= StressMinutes * 60) Stage(33, "stress drive: time up");
                break;
            default:
                W("stress done drive minutes=" + (StressAge / 60).ToString("0.0", inv) + " pos=" + Where());
                Finish("ok stress drive");
                break;
        }
    }

    void StressCleanup()
    {
        if (!stressOn) return;
        stressOn = false;
        try { Function.Call(Hash.CLEAR_PED_TASKS, PlayerPed()); } catch { }
        try { Function.Call(Hash.CLEAR_PLAYER_WANTED_LEVEL, PlayerId()); } catch { }
        try { Function.Call(Hash.SET_PLAYER_INVINCIBLE, PlayerId(), false); } catch { }
        try { if (stressCar != null && stressCar.Exists()) stressCar.Delete(); } catch { }
        try { if (stressModel != 0) Function.Call(Hash.SET_MODEL_AS_NO_LONGER_NEEDED, stressModel); } catch { }
        stressCar = null;
        W("stress cleaned up (wanted cleared, invincible off)");
    }
}
