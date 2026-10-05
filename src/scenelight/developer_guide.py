"""Offline, searchable help for the public Ren'Py author API."""

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent


@dataclass(frozen=True)
class GuideTopic:
    key: str
    category: str
    title: str
    summary: str
    details: tuple[str, ...] = ()
    example: str = ""
    placement: str = ""
    keywords: str = ""


def _topic(key, category, title, summary, *details, example="", placement="", keywords=""):
    return GuideTopic(
        key, category, title, summary, details, dedent(example).strip(), placement, keywords
    )


START = "Start here"
COMMANDS = "Lighting commands"
SETTINGS = "Lighting settings"
WORKFLOW = "Project workflow"
CATEGORIES = (START, COMMANDS, SETTINGS, WORKFLOW)
STORY = "Inside an existing label in your .rpy story file. Keep the leading $ and the label's indentation."
INIT = "At the top level of your own .rpy file under game/. The example includes its init python block. Replace image names with yours."

_INTRO = (
    _topic(
        "start",
        START,
        "Set up your mod",
        "Automatic lighting works without adding commands to your story.",
        "1. Choose For mod developers in the main window, then select your project folder.",
        "2. Scan and review character tags. A tag such as hero covers hero happy, hero worried, and its other expressions. Leave UI, stickers, and props unchecked.",
        "3. Choose Install developer API. Then launch your game and check a scene with a background and character.",
        "Use the commands here when you want extra control. Installation adds game/scenelight_runtime/; your existing scene, show, hide, ATL, and transitions keep their normal syntax.",
        keywords="install beginner quickstart getting started setup",
    ),
    _topic(
        "first-command",
        START,
        "Your first command",
        "Lower the lighting strength for part of your story, then restore it.",
        "Install the developer API first. Put the first line where the change should begin and clear_scene() where it should end. A new Ren'Py scene statement does not automatically clear this override.",
        "Copy example copies text only. It does not run a command or edit your game.",
        example="""
            $ scenelight.scene(strength=0.8)
            # Your dialogue goes here.
            $ scenelight.clear_scene()
        """,
        placement=STORY,
        keywords="example beginner code paste scripting",
    ),
    _topic(
        "precedence",
        START,
        "Which setting wins?",
        "Rules apply from broad defaults to the most specific image.",
        "Project defaults → background → scene → character → exact image. A later rule replaces only the settings it contains. Repeated calls at the same scope merge their settings.",
        "scenelight.off() is an exception: it bypasses lighting for the sequence even if a character or image rule enables it.",
        "An authored strength replaces Preview's saved strength at that scope. The player's master strength still multiplies the result. Rule state supports save/load and rollback.",
        keywords="scope priority override inheritance save load rollback",
    ),
)

_COMMANDS = (
    _topic(
        "configure",
        COMMANDS,
        "Set project defaults",
        "scenelight.configure(**settings)",
        "Set a reusable starting point for your mod. More specific background, scene, character, or image rules can override these values.",
        "Alias: scenelight.defaults(**settings).",
        example="""
            init python:
                scenelight.configure(strength=1.0, color_adaptation=0.78)
        """,
        placement=INIT,
        keywords="global whole game defaults configure",
    ),
    _topic(
        "scene",
        COMMANDS,
        "Adjust one sequence",
        "scenelight.scene(**settings)",
        "Changes the current sequence until you call clear_scene(). It persists across scene statements; clear it explicitly when the sequence ends.",
        "Negative exposure_bias darkens the result. Positive values brighten it.",
        example="""
            $ scenelight.scene(exposure_bias=-0.2, strength=0.9)
            # Your scene continues here.
            $ scenelight.clear_scene()
        """,
        placement=STORY,
        keywords="scene sequence temporary brightness darker brighter",
    ),
    _topic(
        "background",
        COMMANDS,
        "Adjust one background",
        "scenelight.background(name, **settings)",
        "Use a reusable rule whenever this background appears. The leading bg in the background name is optional.",
        example="""
            init python:
                scenelight.background("bg street_night", exposure_bias=-0.2)
        """,
        placement=INIT,
        keywords="background room environment night",
    ),
    _topic(
        "character",
        COMMANDS,
        "Adjust one character",
        "scenelight.character(tag, **settings)",
        "Applies to every pose and expression using this image tag. Use the image tag, not the dialogue speaker's display name.",
        example="""
            init python:
                scenelight.character("hero", strength=0.9)
        """,
        placement=INIT,
        keywords="character tag sprite poses expressions",
    ),
    _topic(
        "image",
        COMMANDS,
        "Adjust one exact image",
        "scenelight.image(name, **settings)",
        "Targets one full registered Ren'Py image name. Other expressions keep their existing rules.",
        example="""
            init python:
                scenelight.image("hero happy", rim_strength=0.8)
        """,
        placement=INIT,
        keywords="image exact expression pose",
    ),
    _topic(
        "off",
        COMMANDS,
        "Turn lighting off",
        "scenelight.off()",
        "Bypasses lighting for the sequence. Use clear_scene() afterward to return to your inherited settings.",
        "Alias: scenelight.disable().",
        example="""
            $ scenelight.off()
            # Your unlit sequence goes here.
            $ scenelight.clear_scene()
        """,
        placement=STORY,
        keywords="disable bypass turn off unlit stop",
    ),
    _topic(
        "on",
        COMMANDS,
        "Turn lighting on",
        "scenelight.on()",
        "Sets enabled=True at the scene scope. Other scene adjustments remain. Character or image exclusions still apply.",
        "Use clear_scene() to remove all scene overrides instead. Alias: scenelight.enable().",
        example="$ scenelight.on()",
        placement=STORY,
        keywords="enable turn on resume",
    ),
    _topic(
        "clear-scene",
        COMMANDS,
        "Restore scene lighting",
        "scenelight.clear_scene()",
        "Removes every scene override, including an off() bypass. Lighting returns to the remaining project, background, character, and image rules.",
        example="$ scenelight.clear_scene()",
        placement=STORY,
        keywords="clear_scene undo restore temporary sequence end reset scene",
    ),
    _topic(
        "clear-rules",
        COMMANDS,
        "Remove a saved rule",
        "Clear only the scope you want to restore.",
        "Each line below is independent. Keep the one you need. Clearing a rule restores inherited values; it does not turn lighting off.",
        example="""
            $ scenelight.clear_defaults()
            $ scenelight.clear_background("street_night")
            $ scenelight.clear_character("hero")
            $ scenelight.clear_image("hero happy")
        """,
        placement=STORY,
        keywords="clear_defaults clear_background clear_character clear_image remove override",
    ),
    _topic(
        "reset",
        COMMANDS,
        "Reset all lighting rules",
        "scenelight.reset()",
        "Clears project, background, scene, character, and image lighting rules. Automatic lighting remains available. The player's master preference remains in place.",
        example="$ scenelight.reset()",
        placement=STORY,
        keywords="reset all clear defaults",
    ),
    _topic(
        "state",
        COMMANDS,
        "Inspect active rules",
        "scenelight.state()",
        "Returns a copy of the current lighting rules. Editing the returned copy does not change active lighting.",
        example="$ current_rules = scenelight.state()",
        placement=STORY,
        keywords="state inspect debug current rules troubleshooting",
    ),
    _topic(
        "modes",
        COMMANDS,
        "Choose a lighting mode",
        "Physical, Cinematic, or Separate.",
        "Physical follows the measured environment and automatically separates strong, distinct colored sources. Cinematic uses a restrained treatment with reduced strength and exposure. Separate emphasizes individual light colors.",
        "Setting light_mode resets that scope's lighting values to the preset, then applies explicit settings from the same call. Physical and Separate reset strength to 1.0; Cinematic uses 0.72 unless you provide strength.",
        "Mode aliases: combined / realistic → physical; individual / creative → separate.",
        example='$ scenelight.scene(light_mode="cinematic", strength=0.84)',
        placement=STORY,
        keywords="light_mode physical cinematic separate combined realistic individual creative preset",
    ),
    _topic(
        "exclude",
        COMMANDS,
        "Exclude an image tag",
        "Keep a sticker or special character image unlit.",
        "Prefer leaving UI and props unchecked during Setup. Use a rule when you need a scripted exclusion for an otherwise selected tag.",
        example="""
            init python:
                scenelight.character("hero_sticker", enabled=False)
        """,
        placement=INIT,
        keywords="exclude ui props sticker flat disable character",
    ),
    _topic(
        "register",
        COMMANDS,
        "Register another tag",
        "scenelight_register_tag(tag)",
        "Routes another registered character image tag through SceneLight unless explicitly unchecked in Characters…. Recheck and update to enable an excluded family. Use Check new assets → Update SceneLight to prepare matching surface maps for new images.",
        example="""
            init python:
                scenelight_register_tag("companion")
        """,
        placement=INIT,
        keywords="register tag new character discover",
    ),
    _topic(
        "player-controls",
        COMMANDS,
        "Player preference controls",
        "scenelight_set_enabled(enabled) / scenelight_set_strength(strength)",
        "These change persistent player preferences, rather than story rules. Reserve them for your own player-facing settings. Strength accepts 0–1.5 and multiplies the authored lighting strength.",
        "For a temporary story change, use scenelight.scene(), off(), or clear_scene() instead.",
        example="""
            textbutton "Lighting on" action Function(scenelight_set_enabled, True)
            textbutton "Lighting off" action Function(scenelight_set_enabled, False)
            textbutton "Normal strength" action Function(scenelight_set_strength, 1.0)
        """,
        placement="Inside your own Ren'Py screen, with the screen's indentation.",
        keywords="persistent preferences settings screen player master strength",
    ),
)

# One searchable entry per setting; examples use the same public scene API.
_SETTING_ROWS = (
    (
        "enabled",
        "Enable this scope",
        "True or False",
        "True",
        "Enable or bypass lighting at this scope. Scene-level False also overrides character and image rules.",
        "on off boolean",
    ),
    (
        "strength",
        "Overall lighting strength",
        "0–2",
        "0.8",
        "Blend the overall relighting effect. 1 is normal strength; 0 removes the lighting contribution.",
        "lighting_strength intensity amount",
    ),
    (
        "auto_strength",
        "Automatic exposure matching",
        "0–2",
        "0.8",
        "Control how strongly the sprite follows the scene's automatically estimated exposure.",
        "exposure brightness auto",
    ),
    (
        "exposure_bias",
        "Brightness adjustment",
        "−4–4 stops",
        "0.2",
        "Brighten with a positive value or darken with a negative value. This is exposure compensation, not a replacement for the environment.",
        "exposure bright dark brightness",
    ),
    (
        "ambient_strength",
        "Ambient illumination",
        "0–2",
        "0.8",
        "Control the broad ambient illumination on the character.",
        "ambient fill illumination",
    ),
    (
        "color_adaptation",
        "Environmental color",
        "0–2",
        "0.65",
        "Control how strongly the character takes on the background's light color. Lower values reduce the tint; higher values strengthen it.",
        "tint green jungle color colour",
    ),
    (
        "contrast_match",
        "Contrast matching",
        "0–2",
        "0.8",
        "Control how strongly character contrast follows the background.",
        "contrast matching",
    ),
    (
        "saturation_match",
        "Saturation matching",
        "0–2",
        "0.8",
        "Control how strongly character saturation follows colored surroundings. Neutral backgrounds preserve the artwork's color.",
        "saturation colorful colourful muted",
    ),
    (
        "highlight_rolloff",
        "Highlight softness",
        "0–2",
        "1.2",
        "Soften newly added highlights while preserving brightness and shading already painted into the sprite.",
        "bright highlights rolloff",
    ),
    (
        "key_strength",
        "Directional light",
        "0–2",
        "0.8",
        "Control the response to the scene's main light direction.",
        "key directional side light",
    ),
    (
        "ray_shadow_strength",
        "Directional self-shadows",
        "0–2",
        "0.5",
        "Control directional shadows estimated from the sprite's surface.",
        "ray shadow self shadowing",
    ),
    (
        "ambient_occlusion",
        "Shading in recesses",
        "0–2",
        "0.3",
        "Control shading in estimated recesses of the character's surface.",
        "ambient occlusion ao depth",
    ),
    (
        "probe_strength",
        "Surrounding light samples",
        "0–2",
        "0.5",
        "Control the contribution from surrounding light samples.",
        "probe local sample environment",
    ),
    (
        "bounce_strength",
        "Bounce light",
        "0–2",
        "0.3",
        "Control indirect light bouncing from the environment.",
        "bounce reflected indirect",
    ),
    (
        "specular_strength",
        "Surface highlights",
        "0–2",
        "0.25",
        "Control specular highlights on the estimated character surface.",
        "specular shine glossy",
    ),
    (
        "rim_strength",
        "Edge lighting",
        "0–2",
        "0.7",
        "Control light along the character's edges.",
        "rim edge outline",
    ),
    (
        "wrap_strength",
        "Color around the silhouette",
        "0–2",
        "0.4",
        "Control environmental color wrapping around the silhouette.",
        "wrap silhouette spill tint",
    ),
    (
        "grain_match",
        "Background grain",
        "0–2",
        "0.5",
        "Control matching of background grain on the character.",
        "grain noise texture",
    ),
    (
        "shadow_strength",
        "Overall shadows",
        "0–2",
        "0.6",
        "Control the overall contribution from shadows.",
        "shadow darkness shade",
    ),
    (
        "individual_light_colors",
        "Separate light colors",
        "0–2",
        "1.0",
        "Emphasize separation of individual source colors for a more stylized result.",
        "separate_light_colors stylized creative colour",
    ),
    (
        "adaptive_light_colors",
        "Automatic color separation",
        "0–2",
        "1.0",
        "Automatically separate distinct colored light sources. Set 0 to disable this separation; environmental color adaptation remains a separate setting.",
        "adaptive automatic coloured colors lamps",
    ),
)

_SETTING_ROWS += (
    (
        "glow_red",
        "Custom glow · red",
        "0–1",
        "0.1",
        "Red channel of the sprite and halo color. Set glow_color_mix=1 and glow_strength above zero to see it.",
        "glow tint color red",
    ),
    (
        "glow_green",
        "Custom glow · green",
        "0–1",
        "0.4",
        "Green channel of the sprite and halo color. Independent of light cast onto other characters.",
        "glow tint color green",
    ),
    (
        "glow_blue",
        "Custom glow · blue",
        "0–1",
        "1.0",
        "Blue channel of the sprite and halo color. Independent of light cast onto other characters.",
        "glow tint color blue",
    ),
    (
        "glow_color_mix",
        "Use custom glow color",
        "0–1",
        "1.0",
        "Zero uses artwork colors; one uses glow_red/green/blue for the sprite and halo. Values between blend the two. Requires glow_strength above zero.",
        "glow custom color tint artwork mix",
    ),
    (
        "glow_strength",
        "Sprite glow",
        "0–10",
        "0.8",
        "Make this sprite luminous and add a soft halo in its own colors. Zero disables glow. Independent of light cast onto other characters.",
        "glow fire flame emissive halo",
    ),
    (
        "glow_radius",
        "Halo spread",
        "0–2",
        "1.0",
        "At 1.0, the halo reaches 4% of the shorter sprite canvas edge. Leave transparent padding around the art. Zero keeps the luminous sprite without a halo.",
        "glow blur radius padding",
    ),
    (
        "emission_strength",
        "Light cast onto characters",
        "0–2",
        "1.0",
        "Illuminate other selected sprites from this sprite's screen center. Zero disables emitted light without turning off its own glow. Up to four visible sources; strongest sources take priority.",
        "cast light fire torch nearby emission",
    ),
    (
        "emission_radius",
        "Emitted light reach",
        "0–2",
        "0.35",
        "Reach measured in screen heights. Light fades smoothly to zero at this distance. Hidden sprites do not emit light. This is a 2D light without wall occlusion.",
        "radius distance falloff range",
    ),
    (
        "emission_red",
        "Emitted light · red",
        "0–2",
        "1.0",
        "Red intensity of the light cast onto other sprites. The sprite's own halo follows its artwork colors.",
        "light color red",
    ),
    (
        "emission_green",
        "Emitted light · green",
        "0–2",
        "0.35",
        "Green intensity of the light cast onto other sprites.",
        "light color green",
    ),
    (
        "emission_blue",
        "Emitted light · blue",
        "0–2",
        "0.08",
        "Blue intensity of the light cast onto other sprites.",
        "light color blue",
    ),
)

_SETTING_ROWS += (
    (
        "light_color_red",
        "Background color target · red",
        "0–1",
        "0.25",
        "Red channel of the light color to adjust. The light_color='#4080FF' shorthand sets all three channels.",
        "background blue hex color cast target",
    ),
    (
        "light_color_green",
        "Background color target · green",
        "0–1",
        "0.5",
        "Green channel of the selected background light color.",
        "background hex color cast target",
    ),
    (
        "light_color_blue",
        "Background color target · blue",
        "0–1",
        "1.0",
        "Blue channel of the selected background light color.",
        "background blue hex color cast target",
    ),
    (
        "light_color_amount",
        "Selected background color influence",
        "−1–1",
        "-0.5",
        "Negative reduces the selected color cast toward neutral; positive strengthens it. Zero is unchanged. This targets incoming light, not colors painted on the sprite or background.",
        "background blue hex less more remove tint color influence",
    ),
    (
        "light_color_tolerance",
        "Similar background colors",
        "0–1",
        "0.25",
        "Widen the hue match around the selected light color. Nearby shades match softly. Gray targets have no color cast to adjust.",
        "background color hue tolerance similar range",
    ),
)

_SETTINGS = tuple(
    _topic(
        "setting-" + name,
        SETTINGS,
        title,
        name,
        description,
        f"Range: {limits}. Numeric values are clamped to the accepted range. The value below is an example, not a required default.",
        "Works with configure(), background(), scene(), character(), and image(). Use clear_scene() when a temporary change should end.",
        example=f"$ scenelight.scene({name}={value})",
        placement=STORY,
        keywords=keywords,
    )
    for name, title, limits, value, description, keywords in _SETTING_ROWS
)

_SETTINGS += (
    _topic(
        "setting-glow_rules",
        SETTINGS,
        "Glow only selected colors",
        "glow_rules",
        "Add independent color glow rules to one character or exact image. Matching uses the original artwork, not the scene's lighting color. Nearby shades match smoothly; transparent pixels cannot become sources.",
        "Each rule has a name, enabled switch, RGB color (0–1 per channel), strength (0–10), radius (0–2), tolerance (0–1), and softness (0–1). Tolerance widens the color range; softness feathers its edge. Zero radius keeps the glow inside the artwork.",
        "Preview → Calibrate → Color glow offers Add, Duplicate, Remove, and live sliders for the loaded sprite. Save profile or Export config retains these settings; use the API for per-character or per-image targets. Rules add together; more active rules take more rendering time.",
        "Use glow_rules=[] to clear the rules for that target. This replaces the inherited list; other lighting controls and other sprites stay independent. Whole-sprite glow and light cast onto neighbors are separate controls.",
        example="""
            init python:
                scenelight.image("hero magic", strength=0.7, glow_rules=[
                    {"name": "Red gems", "color": [1.0, 0.05, 0.02],
                     "tolerance": 0.15, "softness": 0.1, "strength": 0.8, "radius": 1.0},
                    {"name": "Blue markings", "color": [0.05, 0.2, 1.0],
                     "tolerance": 0.2, "softness": 0.1, "strength": 0.5, "radius": 0.6}
                ])
        """,
        placement=INIT,
        keywords="selective glow color colour red blue mask hue tolerance range softness multiple rules",
    ),
)

_WORKFLOW = (
    _topic(
        "sprite-glow",
        WORKFLOW,
        "Glowing fire, symbols, and effect sprites",
        "Choose self glow, nearby light, or both for each image.",
        "Include the effect tag in Setup's character selection so it receives SceneLight. Put the rules below in an init python block. Use character() for every expression of a tag, or image() for one exact image.",
        "The two strengths are independent: glow_strength=0 emits light without a halo; emission_strength=0 glows without lighting neighbors. Zero both restores ordinary lighting. Each character and image keeps its own full lighting settings.",
        "Preview shows one sprite. Use the Artwork-to-color slider to blend a tint, with Sprite glow above zero (up to 10). Check cast light onto other characters in the mod. Use character() or image() to set independent per-target lighting. Leave transparent padding around effect art for the halo.",
        example="""
            init python:
                scenelight.character("hero", strength=0.65, rim_strength=0.4)
                scenelight.image("hero worried", strength=0.9, exposure_bias=-0.15)
                scenelight.image("fire burning", glow_strength=0.8, glow_radius=1.2,
                    emission_strength=1.0, emission_radius=0.45,
                    emission_red=1.0, emission_green=0.35, emission_blue=0.08)
        """,
        placement=INIT,
        keywords="glow flame fire torch effect sprite per sprite independent lighting",
    ),
    _topic(
        "selection",
        WORKFLOW,
        "Choose characters and discover new ones",
        "Reopen Characters… beside the game folder in either Setup mode.",
        "Characters… refreshes discovery before showing the checklist. Automatically include new characters on scan / update is on for new projects. Unchecked families stay excluded. Turn it off to keep only your chosen tags. Existing manual selections stay manual.",
        "For an installed project, Apply selection & update prepares the changed selection. After adding or replacing game assets, run Scan/Update; SceneLight does not watch the project folder continuously. The update keeps your lighting profile and saves.",
        "Place scenelight.json beside game/, not inside it. Each tag covers its expressions and poses. Merge these keys into an existing configuration instead of replacing its other settings.",
        example="""
            {
              "auto_include_new_characters": true,
              "character_tags": ["hero", "companion"],
              "excluded_character_tags": ["sticker"]
            }
        """,
        placement="scenelight.json in your project root, beside game/. This is JSON.",
        keywords="selection tags config json manual automatic exclude new character rescan update version control",
    ),
    _topic(
        "preview",
        WORKFLOW,
        "Preview your lighting",
        "Try a background and sprite before changing your story.",
        "Open Settings → Tools → Open Preview & Calibrator. Load your background and sprite, move the character, and adjust the lighting.",
        "Use Export config to save the settings into your project's scenelight.json. After changing assets or configuration, return to developer mode and update the installation.",
        keywords="preview calibrator profile export config calibration test",
    ),
    _topic(
        "shaders",
        WORKFLOW,
        "Use other shaders",
        "Shader placement controls whether it runs before or after lighting.",
        "An outer show ... at shader receives the lit sprite. A shader inside an image declaration runs before SceneLight. Use mesh True for a model shader's separate rendering pass.",
        "If a second shader also simulates lighting, both effects contribute. Use a scene or character bypass when appropriate, and test with your actual transforms. Custom scene-list replacements need their own compatibility check.",
        keywords="shaders transforms atl mesh True MVN compatibility composition",
    ),
    _topic(
        "updates",
        WORKFLOW,
        "Add assets or update",
        "Prepare new art through the existing developer workflow.",
        "Choose For mod developers → Check new assets → Update SceneLight. Review new character tags. Existing poses may use generic surface geometry until their matching maps are prepared.",
        "Updates reuse valid analysis. If a SceneLight-owned runtime file was edited, the update stops so the change is not overwritten. Put your story rules in your own .rpy files.",
        keywords="update refresh new assets expressions pose maps regenerate modified files",
    ),
    _topic(
        "shipping",
        WORKFLOW,
        "Before you ship",
        "Test the game you will distribute, including its lighting files.",
        "Include the installed game/scenelight_runtime/ files in your Ren'Py build. Keep your own story rules. Check custom build/archive exclusions so generated runtime files and maps are not omitted.",
        "Extract the built game into a fresh folder and launch it. Check movement, expression changes, transitions, skipping, resizing, UI, custom shaders, save/load, and rollback.",
        "Test on your target GPUs and Ren'Py version. CUDA only accelerates preparation; players do not need CUDA for lighting. See the bundled docs/BETA_VALIDATION.md for tested coverage and limits.",
        "The full offline documentation is included in the download's docs folder: AUTHOR_QUICKSTART.md and MOD_AUTHOR_API.md.",
        keywords="ship release export build distribute package test offline documentation requirements GPU CUDA",
    ),
)

_INSPECTOR = (
    _topic(
        "inspector",
        COMMANDS,
        "Open the in-game lighting inspector",
        "scenelight.inspector()",
        "Shift+F9 also opens it. Select a visible sprite to see every setting, its winning source, and the player master multiplier. All sources lists overridden values too.",
        "Newly executed rules record their .rpy filename and line. Older saved rules may not have a recorded location. Nested lighting passes and external color grades are included in the diagnostic report.",
        "Edits are temporary and do not change story rules, saves or persistent preferences. Clear all test edits restores the originals; a new game, load or restart also clears them. Closing the panel keeps test edits active with a visible badge.",
        "Drag numeric sliders to adjust lighting live, or use Edit for an exact value. Checks highlights observed conflicts and lets you add notes or include a screenshot in the support report.",
        "Export report saves one scenelight-support ZIP in the game's main folder with readable HTML, settings, sources, build identity, engine logs and samples. A JSON copy remains available for Activity exports. Source artwork, scripts and saves are excluded; a screenshot is optional.",
        example="$ scenelight.inspector()",
        placement=STORY,
        keywords="debug inspect tester hidden settings priority override diagnostic report",
    ),
    _topic(
        "inspect",
        COMMANDS,
        "Read effective lighting and its sources",
        "scenelight.inspect(tag=None)",
        "Returns a diagnostic snapshot for all visible sprites, or one tag. Includes rules, temporary edits, effective/master strengths, last drawn state, map availability and external color grading. It does not edit the game.",
        example='$ lighting_report = scenelight.inspect("hero")',
        placement=STORY,
        keywords="debug inspect snapshot report effective source actual",
    ),
    _topic(
        "background-color",
        COMMANDS,
        "Reduce or increase one background color",
        "Select a hex color and adjust its influence on sprites.",
        "light_color accepts #RRGGBB. light_color_amount runs from -1 (neutralize matching light color) through 0 (unchanged) to +1 (stronger color). light_color_tolerance widens the soft hue match. Light luminance is retained; this is separate from exposure or glow.",
        "Use this per background, or the existing scene, character and image scopes. Preview has the same controls in Calibrate → Background color.",
        example='init python:\n    scenelight.background("lake", light_color="#4080FF", light_color_amount=-0.5, light_color_tolerance=0.25)',
        placement=INIT,
        keywords="background blue hex tint color cast more less",
    ),
)

TOPICS = _INTRO + _COMMANDS + _INSPECTOR + _SETTINGS + _WORKFLOW


def search_topics(query: str = "", category: str = "All topics") -> tuple[GuideTopic, ...]:
    """Match every query word across names, explanations, aliases, and examples."""
    terms = query.casefold().split()
    matches = []
    for topic in TOPICS:
        if category != "All topics" and topic.category != category:
            continue
        heading = (topic.title + " " + topic.summary).casefold()
        searchable = " ".join(
            (heading, *topic.details, topic.example, topic.placement, topic.keywords)
        ).casefold()
        if all(term in searchable for term in terms):
            # A command's own entry should precede incidental mentions in an
            # example. Stable sorting preserves the reading order otherwise.
            rank = 0 if all(term in heading for term in terms) else 1
            matches.append((rank, topic))
    return tuple(topic for _rank, topic in sorted(matches, key=lambda match: match[0]))
