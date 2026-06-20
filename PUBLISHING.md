# Publishing Ultimate Measure

Notes for getting this into the Glyphs Plugin Manager. None of it needs Xcode or
an Apple Developer account: the bundle already contains the generic Python loader
stub, and the Plugin Manager installs via `git clone` (which doesn't quarantine
files), so the unsigned bundle loads cleanly.

## Automated runbook (for Claude Code)

Run from inside this `UltimateMeasure/` folder. Precondition (human, once):
`gh auth login`. Everything else is scriptable. The repo is already git-inited,
on branch `main`, with one commit.

```bash
# 1. Derive the GitHub handle and fill the placeholders in this file's entry.
HANDLE=$(gh api user --jq .login)

# 2. Create the public repo from this folder and push.
gh repo create UltimateMeasure --public --source=. --remote=origin --push

# 3. Fork + clone the registry (default branch is glyphs3).
gh repo fork schriftgestalt/glyphs-packages --clone=true --remote=false
cd glyphs-packages

# 4. Edit packages.plist: insert the entry block below INTO the `plugins = ( … );`
#    array (NOT the `scripts` or modules arrays) — immediately before the `);`
#    that closes the plugins array. Replace YOUR-USERNAME with $HANDLE. Keep the
#    trailing comma after the closing brace.

# 5. Validate the way CI does (Parse Packages.command is just a GUI wrapper).
plutil -lint packages.plist
swift validate-paths.swift            # optional; needs the repo pushed (step 2)
swift validate-install-names.swift    # optional

# 6. Branch, commit, push, open the PR against glyphs3.
git checkout -b add-ultimate-measure
git add packages.plist
git commit -m "Add Ultimate Measure"
git push -u origin add-ultimate-measure
gh pr create --repo schriftgestalt/glyphs-packages --base glyphs3 \
  --title "Add Ultimate Measure" \
  --body "Adds Ultimate Measure, a reporter plugin for live stem/edge and X/Y measurement. Repo: https://github.com/$HANDLE/UltimateMeasure"
```

Two things Claude Code cannot do for you: `gh auth login` (interactive, once),
and getting the PR merged — that's a human maintainer on the Glyphs side. It can
do everything up to and including opening the PR.

The single fiddly step is #4: `packages.plist` is large and has multiple arrays
(`plugins`, `scripts`, plus a modules list). The entry must go inside the
`plugins = ( … )` array, just before its closing `);`.

## 1. Publish the repo

Push this folder to a public GitHub repo (repo root = this folder, so the bundle
`UltimateMeasure.glyphsReporter` sits at the top level). Bump `CFBundleVersion`
in `Contents/Info.plist` for every release — that number drives users' update
prompts.

## 2. Add to the Plugin Manager registry

Fork **https://github.com/schriftgestalt/glyphs-packages** (default branch is
`glyphs3`), add the entry below to the end of the `plugins = ( … )` list in
`packages.plist` (mind the trailing comma), run `Parse Packages.command` to
validate locally, then open a pull request against `glyphs3`.

```
{
    titles = {
        en = "Ultimate Measure";
    };
    url = "https://github.com/YOUR-USERNAME/UltimateMeasure";
    path = "UltimateMeasure.glyphsReporter";
    descriptions = {
        en = "*View > Ultimate Measure*. Hold Option for live stem and edge measurement and full cross-section slices (Option+Shift); with a node selected, shows X/Y distances to the node, handle, corner or overlap crossing under the cursor.";
    };
    identifier = "ultimate-measure";
    screenshot = "https://raw.githubusercontent.com/YOUR-USERNAME/UltimateMeasure/main/screenshot.gif";
},
```

(Replace `YOUR-USERNAME` in both the `url` and `screenshot` lines with your GitHub
handle. The `screenshot` URL assumes the default branch is `main`.)

Required keys: `titles`, `url`, `descriptions`, and (for plug-ins) `path` — the
path to the bundle inside the repo. The URL has no trailing slash. The convention
is to name the menu path in the description and italicise UI text with `*…*`.

Optional keys worth adding: `screenshot = "https://raw.githubusercontent.com/YOUR-USERNAME/UltimateMeasure/main/screenshot.gif";`
(a demo image — strongly recommended), `identifier` (a short ID; enables the
`glyphsapp3://showplugin/ultimate-measure` deep link), and
`minGlyphsVersion = "3.0";` if you want to gate older Glyphs out. Full key list is
in the registry's own README.

## What happens after the PR

It's not fully automatic — a person merges it. When you open the PR, GitHub
Actions runs the registry's checks automatically (property-list lint, install-name
and path validation), so you'll see green ticks or specific errors within a minute
or two; fix anything red and push again. Then a Glyphs maintainer reviews and
merges. There's no published turnaround — it can be a day or two, sometimes
longer depending on their availability. If it sits, a polite nudge on the
[Glyphs Forum](https://forum.glyphsapp.com) is the accepted way to follow up.

Once merged, it appears in everyone's Plugin Manager (Glyphs may cache the index
briefly). After that, releases are automatic: push a commit with a bumped
`CFBundleVersion` and users get the update prompt — no new PR needed unless you
change the registry entry itself.

## 3. Courtesy

Ultimate Measure derives from Rafał Buchner's StemThickness (Apache 2.0). Worth
telling him you've published an extended variant, or offering the Option-gating
upstream — both as etiquette and to avoid two near-identical plugins in the list.

## Optional: signing for zip distribution

Handing the bundle out as a `.zip` works fine in practice — recipients unzip,
double-click, restart Glyphs. A browser-downloaded zip does carry macOS's
quarantine flag, but it rarely blocks a plugin bundle (Glyphs loads it
internally, and the stub is ad-hoc signed); if a stricter Mac does complain, the
`xattr -dr com.apple.quarantine …` one-liner from the README clears it.

Signing with a Developer ID (via `codesign`, or by building from the GlyphsSDK
Xcode template with your team selected) only buys you *zero-friction* zip
installs for everyone, with no quarantine prompt ever. It's optional, and not
needed at all for Plugin Manager distribution.
