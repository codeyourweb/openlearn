# Screenshot baseline

`tools/visual/shots.py` captures the read paths at two widths in both themes, then
compares a later run against the reference pixel by pixel. It exists so a change
can claim "nothing moved" instead of "I did not notice anything moving".

Images are not committed: a full-page capture of eleven views at two widths and
two themes weighs around 35 MB. The reference is a directory you keep where you
work, and you regenerate it from the release you trust.

## Workflow

    # 1. reference, taken from the code you ship today
    git stash            # or check out the previous tag
    python tools/visual/shots.py --base-url http://<instance>:8000 --out .shots/ref

    # 2. candidate, taken from your branch
    git stash pop
    python tools/visual/shots.py --base-url http://<instance>:8000 \
        --out .shots/after --compare .shots/ref

The comparison prints, per view, the share of pixels that changed and the
bounding box of the change, and writes a black-and-white mask of every differing
region into `.shots/diff/`. Exit status is 1 when anything differs, so it can
gate a merge once a reference is checked in somewhere stable.

## What makes it reproducible

* one instance, seeded with the demo catalogue — the same content every time;
* `reduced_motion="reduce"`, which the interface already honours, so the landing
  rotator and the product studio hold a still frame;
* a freeze stylesheet that zeroes animations and transitions (it needs
  `bypass_csp`, since instances send `style-src 'self'`);
* French interface, fixed viewport per width, `networkidle` plus a short settle.

## Reading the result

A few pixels of antialiasing are ignored (differences below a threshold of 12 out
of 255, and the share is reported so a one-pixel edge does not look like a
regression). Anything above a few hundredths of a percent is a real change and
must be explained in the commit — the contrast fixes of the accessibility work are
the expected example.
