---
name: verifying-rendered-ui
description: >
  Use after building or changing any chart, dashboard or visual layout, and when
  a user says a chart "isn't working" but the data looks right. Explains why a
  text snapshot cannot tell you a chart rendered, and what to measure instead.
verify: "test -d $HOME/projects/bb-plugin-browser"
verified: 2026-08-13
---

# A text snapshot cannot tell you a chart rendered

A DOM text snapshot returns labels, axis values, legends and numbers. It returns
all of them identically whether the bars are 140 pixels tall or **zero**. So a
chart can be completely invisible while every automated check you ran says it is
fine — which is how one survived two review rounds here before a human said "the
charts are not working".

**Measure the boxes.** Get `getBoundingClientRect()` for the marks themselves,
not the container:

```js
[...document.querySelectorAll(".chart .bar")].map((n) => {
  const r = n.getBoundingClientRect();
  return { w: Math.round(r.width), h: Math.round(r.height) };
});
```

A bar with `h: 0` is a bug. A bar with `w: 0` in a horizontal chart is a bug.
Distinguish those from a legitimately empty category — an empty day *should*
measure zero, so check that the populated ones do not.

## The specific trap: percentage height in a flex row

This is the bug, and it is easy to write:

```jsx
<div className="flex h-32 items-end">      {/* row has a height */}
  <div className="flex flex-1 flex-col justify-end">   {/* NO height */}
    <div style={{ height: "60%" }} />       {/* resolves against auto → 0 */}
  </div>
</div>
```

`items-end` makes each flex child size to its content, so the wrapper's height is
auto. A percentage height inside an auto-height parent has nothing to resolve
against and collapses. The wrapper renders, the labels render, the bar does not.

Fix: give the wrapper a definite height — `items-stretch` (the default) plus
`h-full` on the wrapper — and push the mark down with `justify-end`.

Width-percentage bars in a horizontal chart do **not** hit this, because a flex
row's children have a definite width. That asymmetry is why the horizontal bars
looked fine while the vertical ones were empty.

## Verify the whole loop, not the last step

Three things have to be true and they fail independently:

1. **The data arrives** — check the payload, not the render.
2. **The marks have geometry** — measure them.
3. **The control changes the data** — switch the dimension or filter and confirm
   the returned series actually differs. A selector that renders but rebinds
   nothing looks perfect in a snapshot.
