# The GTA VI experience in GTA V Enhanced: what Leonida covers, and what's still missing

The owner's goal: *"make the GTA 6 experience modpack into GTA 5 fully"*. This page compares what makes GTA VI feel
like GTA VI with what Leonida's free packs put into GTA V Enhanced, and says honestly what no free, legitimate mod can
do yet. Written 2026-11-25; GTA VI came out on 19 November 2026 (PS5 / Xbox Series X|S).

**Sources for GTA VI:** Rockstar's own site (rockstargames.com/VI: "Vice City, USA", the characters page "Only in
Leonida" with Vice City, the Leonida Keys, Grassrivers, Port Gellhorn, Ambrosia and Mount Kalaga, the music page) and
its two trailers. Fan wikis and leaks aren't used.

**Rules for the mods:** free, made for GTA V Enhanced (and the owner's game build 1.0.1013.20), from the author's own
page, no re-uploads, nothing leaked. Where two mods do the same job, the better, newer, working one wins.

The packs (Leonida's *Choose mods* page):
- **Leonida Core**: the free, stable base.
- **Leonida Plus**: Core + Immersive Combat, the game's own online interiors, Jason's house.
- **Leonida Showcase (GTA VI)**: Plus + everything below marked *Showcase*, with Performance / Balanced / Ultra.
- Add-ons can be ticked on any pack.

---

## 1. Feature by feature

| GTA VI | Leonida has it | Pack | Still missing |
| --- | --- | --- | --- |
| **The look**: bright Florida sun, deep sunsets, storms, wet roads, ocean | **VisualV** (free weather, light and colour overhaul from Los Angeles photos; no ReShade); Enhanced's own ray-traced reflections on wet roads; **GTA V Remastered**'s thousands of extra trees and props | Showcase (VisualV and Forza Horizon 6 Roads default, Remastered) | NaturalVision Enhanced's textures and models are paid (VisualV is its free stand-in). Moving ocean waves and road spray are only in AuraV's patron edition |
| ... on an NVIDIA RTX card | **AuraV Lite**: free path-traced light, shadows and reflections, new sky and clouds, rain on the lens | add-on *Look* | not for GTX cards; untested together with VisualV and on 1.0.1013.20 |
| **HUD and minimap** | **GTA VI-Inspired HUD**: GTA VI-style HUD, 3D minimap with teal / pink routes, notifications, WASTED / BUSTED in GTA VI's style | Core | — |
| **Two protagonists** | the HUD's GTA VI character switcher (cards for Michael, Franklin, Trevor, **Jason**, **Lucia**) | Core | Jason's and Lucia's full models are paid (Patreon); the free *MP Jason & Lucia V* heads are an add-on (*Characters*) |
| **The phone** | **iOS 26 App Icons**: modern icons on the iFruit phone | Showcase | GTA VI's phone apps and in-game social media: no free mod |
| **Camera and combat** | **GTA VI Combat Camera** (aim camera further back, centred crosshair); **Camera Flinch** (shake when hit); the HUD's crosshair with kill marks, Focus, crouch / crawl, carry all weapons; **Immersive Combat** (weapons and damage) | Core / Showcase / Plus | — (*Better fist fighting* is an add-on) |
| **Movement and physics** | **NextGen Euphoria** (more natural falls, stumbles and hit reactions); the HUD's sit anywhere, crouch, crawl, gym, diving | Core | GTA VI's new on-foot animations and climbing. *Acrobatics & Movement Control* was looked at but left out: it ships another author's file (SimpleFootControls.asi) "since it is no longer available on site", which breaks the no-re-upload rule |
| **Vehicles and handling** | **Drive V** (realistic handling, damage and top speeds, 7.4 on your build); the HUD's fuel with the pump nozzle, nitrous and Leonida Customs; **Benny's**; the **dynamic first-person car camera** | Core / Showcase | GTA VI's own cars. Free GTA VI-inspired add-on cars exist on gta5-mods (e.g. STK10's) but aren't checked yet |
| **Traffic and people** | **All MP Vehicles in SP** (online cars in traffic and parking lots, no blips); **Resource Extensions** densities per variant (Balanced: 1.5x people and parked cars, 1.25x traffic; Ultra: 2x / 1.5x); the HUD's dog walkers and people who remember you | Core, densities in Plus / Showcase | GTA VI's crowds on the beaches |
| **City life** | walk-in **Burger Shot**, **Up-n-Atom** and two **24/7** shops built into the map; the game's own online interiors (**Enable All Interiors**); **street food** carts; **ActionsV** (smoke, drink, guitar, binoculars); **food delivery** and **rideshare** jobs; the HUD's gym, dive shops, gas pumps, bank and Vangelico **heists**; **Map Updates** | Showcase / Plus | beach life and nightlife at GTA VI's scale |
| **Wanted level and police** | the HUD: GTA VI's **wanted box** (what the police know), its police lights at the screen edge and police arrow, police with **stun guns** who only shoot to kill at 3+ stars when you're armed, **surrender** (hold E), calmer streets when you're not wanted | Core | — (*Dispatch Reworked* was looked at: six stars, army jets; it would fight the HUD's own GTA VI police AI, so it's not added) |
| **Radio, sound, music** | the HUD's **radio wheel** with station logos, song and artist, and **On Demand** for your own music (`scripts\Hud\Radio\CustomMusic`) | Core | GTA VI's soundtrack and radio are Rockstar's: put music you own into On Demand. *DeathVI SFX* (GTA VI's death sound) is left out: its page says it's made from the leaked GTA VI sound |
| **Loading and menus** | **Straight To Story Mode** (no legal / splash / landing screens); **GTA VI loading screens** with Rockstar's Vice City pictures (the HUD's own add-on) | Core / Showcase | — |
| **Vice City and Leonida**: the city, the Keys, the swamps (Grassrivers), wildlife | the HUD's "Leonida Customs" and Vice City loading screens; GTA V Remastered's palms and plants | Showcase | **the map itself**: no free, legitimate Vice City / Leonida map exists for GTA V Enhanced. Map ports built from Rockstar's own Vice City files aren't allowed. No alligators, flamingos or airboats either |

---

## 2. What was added for this (2026-11-25)

| Mod | Why | Where |
| --- | --- | --- |
| **GTA VI loading screens** (the HUD's `-LoadingScreens-Enhanced.oiv`, GitHub, automatic download) | GTA VI's loading screens with Rockstar's Vice City pictures, from the HUD author | Showcase default; add-on *Menus, phone & sound* (both editions) |
| **iOS 26 App Icons** (shifuguru, gta5-mods) | a modern phone look, closer to GTA VI's smartphone; tested on Enhanced by its author | Showcase default; add-on *Menus, phone & sound* (both editions) |
| **AuraV Lite** (Kypos, kyposmods.com, free) | path-traced lighting and a new sky for RTX cards; the HUD's guide has a tested section for it | add-on *Look* (Enhanced) |
| Key fix | the HUD reloads its settings on **F10**: ActionsV's menu moves to **F7** and AuraV's to **F11** (locked in their ini files) | all packs |

---

## 3. What you'll notice in game

**Leonida Core**
- GTA VI's HUD and 3D minimap, the WASTED screen, the wanted box and the police lights at the screen edge.
- Hold **Left Alt** for GTA VI's character cards.
- Police tase and arrest you instead of shooting at once; hold **E** to surrender.
- The aim camera sits further back with the crosshair in the middle.
- People fall and stumble more naturally.
- Cars handle heavier and more realistically and dent more.
- Online cars drive around and park, with no blips on the map.
- Fill up at the pump with its nozzle.
- The game starts straight in story mode.

**Leonida Plus** (everything in Core, and)
- The game's online interiors are open in story mode: offices, clubhouses, apartments, the casino.
- Weapons kick harder and hurt more.
- Jason's house.
- On *Balanced* or *Ultra*: noticeably fuller streets and parking lots.

**Leonida Showcase (GTA VI)** (everything in Plus, and)
- A warmer, more natural light and new weathers (VisualV).
- Many more trees and plants (GTA V Remastered).
- GTA VI loading screens.
- Modern phone icons.
- Walk into Burger Shot, Up-n-Atom and two 24/7 shops.
- Buy street food.
- Smoke, drink or play guitar (ActionsV, F7).
- Take food-delivery and rideshare jobs.
- Tune at Benny's.
- The camera shakes when you're hit.
- A first-person car camera that moves with the road.

---

## 4. Honest gaps (no free, legitimate mod yet)

1. **The Vice City / Leonida map.** The biggest one. GTA V's map stays Los Santos.
2. **Ocean waves, road spray, water reflections**: only in AuraV's patron edition; NVE's world textures are paid.
3. **GTA VI's soundtrack and radio**: Rockstar's music. Use On Demand with music you own.
4. **The phone's apps and social media.**
5. **GTA VI's new movement and climbing.**
6. **Wildlife** (alligators, flamingos), airboats and the swamps.
7. **Full Jason and Lucia models**: paid; the free heads are a stand-in.
8. **GTA VI's own cars**: GTA VI-inspired add-on cars exist; they're a candidate for the next round once checked.

Untested on your PC (1.0.1013.20) so far: VisualV, the HUD's loading screens, the iOS icons and AuraV Lite. The HUD and
the Combat Camera were made on 1.0.1158.
