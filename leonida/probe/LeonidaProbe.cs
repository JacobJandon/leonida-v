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
using System;
using System.Globalization;
using System.IO;
using GTA;
using GTA.Math;
using GTA.Native;

public class LeonidaProbe : Script
{
    static readonly string[] Packs = { /*PACKS*/ };
    const string TestCar = "/*CAR*/";
    const double ReadySeconds = 5;     // the player has had control this long
    const double ReadyTimeout = 180;   // waiting for control (then the checks run anyway if the player ped exists)
    const double ModelTimeout = 20;    // waiting for the test car's model
    const double Deadline = 300;       // the whole probe, from its first tick

    readonly string logPath;
    readonly CultureInfo inv = CultureInfo.InvariantCulture;
    DateTime firstTick = DateTime.MinValue, stageAt = DateTime.UtcNow, readySince = DateTime.MinValue;
    int stage, ticks, modelHash;
    Vehicle car;
    bool done;

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
            if (age > Deadline) { Finish("deadline stage=" + stage); return; }
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
                default:
                    Finish("ok");
                    break;
            }
        }
        catch (Exception ex) when (!(ex is System.Threading.ThreadAbortException))  // our own Abort() in Finish: not an error
        {
            W("probe_error stage=" + stage + " " + ex.GetType().Name + ": " + ex.Message.Replace(Environment.NewLine, " "));
            Finish("error");
        }
    }
}
