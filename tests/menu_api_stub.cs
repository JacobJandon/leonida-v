// A stand-in for the parts of Script Hook V .NET's API v3 that leonida/menu/LeonidaMenu.cs uses, so
// tests/test_menu.py can compile the menu with C# 5 (as Script Hook V .NET does) without the game, and run its JSON
// code. Only the names and shapes matter. build/check_menu.py compiles against the real ScriptHookVDotNet3.dll.
// Keep it C# 5 too.
using System;
using System.Windows.Forms;

namespace GTA.Native
{
    public enum Hash : ulong
    {
        ADD_TEXT_COMPONENT_SUBSTRING_PLAYER_NAME, BEGIN_TEXT_COMMAND_DISPLAY_TEXT, DISABLE_ALL_CONTROL_ACTIONS,
        BEGIN_TEXT_COMMAND_GET_SCREEN_WIDTH_OF_DISPLAY_TEXT, END_TEXT_COMMAND_GET_SCREEN_WIDTH_OF_DISPLAY_TEXT,
        DISABLE_CONTROL_ACTION, DRAW_RECT, END_TEXT_COMMAND_DISPLAY_TEXT, GET_IS_LOADING_SCREEN_ACTIVE,
        IS_CONTROL_JUST_PRESSED, IS_DISABLED_CONTROL_JUST_PRESSED, IS_PAUSE_MENU_ACTIVE, NETWORK_IS_SESSION_STARTED,
        PLAY_SOUND_FRONTEND, SET_TEXT_COLOUR, SET_TEXT_FONT, SET_TEXT_JUSTIFICATION, SET_TEXT_SCALE, SET_TEXT_WRAP,
        BEGIN_TEXT_COMMAND_THEFEED_POST, END_TEXT_COMMAND_THEFEED_POST_TICKER, REQUEST_IPL, IS_IPL_ACTIVE,
        IS_DLC_PRESENT, GET_HASH_KEY, PLAYER_PED_ID, DOES_ENTITY_EXIST, IS_PLAYER_PLAYING, PLAYER_ID,
        IS_SCREEN_FADED_IN, GET_CURRENT_LANGUAGE,
    }

    public static class Function
    {
        public static T Call<T>(Hash hash, params object[] args) { return default(T); }
        public static void Call(Hash hash, params object[] args) { }
    }
}

namespace GTA
{
    public abstract class Script
    {
        public int Interval { get; set; }
        public event EventHandler Tick;
        public event EventHandler Aborted;
        public event KeyEventHandler KeyDown;
        public void Abort() { if (Tick != null && Aborted != null && KeyDown != null) { } }
    }
}
