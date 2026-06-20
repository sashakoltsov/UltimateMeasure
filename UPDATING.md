# Updating Ultimate Measure

Once the plugin is in the Plugin Manager, shipping an update is just a push to
`main` — no new registry PR.

## The one rule

Bump **`CFBundleVersion`** in `UltimateMeasure.glyphsReporter/Contents/Info.plist`
every release. That integer is what the Plugin Manager compares to decide an
update is available — forget it and users won't be offered the update even with
new code.

Optionally bump `CFBundleShortVersionString` (the human-facing "1.0") by semver:
patch (`1.0.1`) for fixes, minor (`1.1`) for features, major (`2.0`) for big or
behaviour-changing releases. The two fields don't need to match.

## Steps

1. Edit the code — almost always `Contents/Resources/plugin.py`.
2. Bump the version(s) in `Info.plist` (build number always; short version when
   it's meaningful).
3. Commit and push:
   ```bash
   git add -A
   git commit -m "v1.1 — <what changed>"
   git push
   ```

That's the whole release. The Plugin Manager notices the higher `CFBundleVersion`
and prompts users to update.

## Test before you push

Drop the new `plugin.py` into your installed bundle and restart Glyphs:
`~/Library/Application Support/Glyphs 3/Plugins/UltimateMeasure.glyphsReporter/Contents/Resources/`
Errors print to **Window → Macro Panel** (`UltimateMeasure:` prefix).

## When you DO need another registry PR

Only when you change the *listing* itself — title, description, screenshot URL,
`minGlyphsVersion`, etc. — i.e. the entry in `glyphs-packages/packages.plist`.

Changes to files in *your own* repo (code, README, or even replacing
`screenshot.gif` at the same path) never need a PR: the registry references them
by URL and always pulls the latest.
