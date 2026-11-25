// A tiny stand-in for the parts of Script Hook V .NET's API v3 that leonida/probe/LeonidaProbe.cs uses, so
// tests/test_probe.py can compile the probe with C# 5 (as Script Hook V .NET does) without the game. Only the names
// and shapes matter; nothing here runs. build/check_probe.py compiles against the real ScriptHookVDotNet3.dll.
// Keep it C# 5 too.
using System;

namespace GTA.Math
{
    public struct Vector3
    {
        public float X, Y, Z;
        public Vector3(float x, float y, float z) { X = x; Y = y; Z = z; }
        public static Vector3 operator +(Vector3 a, Vector3 b) { return new Vector3(a.X + b.X, a.Y + b.Y, a.Z + b.Z); }
        public static Vector3 operator *(Vector3 a, float f) { return new Vector3(a.X * f, a.Y * f, a.Z * f); }
    }
}

namespace GTA.Native
{
    public enum Hash : ulong
    {
        DOES_ENTITY_EXIST, GET_HASH_KEY, GET_IS_LOADING_SCREEN_ACTIVE, HAS_MODEL_LOADED, IS_DLC_PRESENT,
        IS_MODEL_A_VEHICLE, IS_MODEL_IN_CDIMAGE, IS_PLAYER_PLAYING, IS_SCREEN_FADED_IN, PLAYER_ID, PLAYER_PED_ID,
        REQUEST_MODEL, SET_MODEL_AS_NO_LONGER_NEEDED,
    }

    public static class Function
    {
        public static T Call<T>(Hash hash, params object[] args) { return default(T); }
        public static void Call(Hash hash, params object[] args) { }
    }
}

namespace GTA
{
    using GTA.Math;

    public abstract class Script
    {
        public int Interval { get; set; }
        public event EventHandler Tick;
        public event EventHandler Aborted;
        public void Abort() { if (Tick != null && Aborted != null) { } }
    }

    public class Entity
    {
        public Vector3 Position { get { return new Vector3(); } }
        public Vector3 ForwardVector { get { return new Vector3(); } }
        public bool Exists() { return true; }
        public void Delete() { }
    }

    public class Ped : Entity { }

    public class HandlingData
    {
        public bool IsValid { get { return true; } }
        public float Mass { get { return 0f; } }
        public float InitialDriveForce { get { return 0f; } }
        public float BrakeForce { get { return 0f; } }
        public float TractionCurveMax { get { return 0f; } }
    }

    public class Vehicle : Entity
    {
        public HandlingData HandlingData { get { return new HandlingData(); } }
    }

    public struct Model
    {
        public Model(int hash) { }
    }

    public class Player
    {
        public Ped Character { get { return new Ped(); } }
    }

    public static class Game
    {
        public static Player Player { get { return new Player(); } }
        public static Version FileVersion { get { return new Version(1, 0); } }
    }

    public static class World
    {
        public static Vehicle CreateVehicle(Model model, Vector3 position) { return new Vehicle(); }
    }
}
